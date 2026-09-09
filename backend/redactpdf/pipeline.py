from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pymupdf

from redactpdf.audit import AuditOptions, audit_pdf_text, build_audit_for_search
from redactpdf.multiline_regex_engine import find_redaction_rectangles_by_regex
from redactpdf.ocr import OCR_MIN_PAGE_SHARE
from redactpdf.opaque import (
    OpaqueRegion,
    UnreliableFont,
    drop_covered,
    drop_fully_covered_pages,
    find_opaque_regions,
    find_unreliable_fonts,
    page_rects_of,
)
from redactpdf.presets import find_redaction_rectangles_for_presets
from redactpdf.redaction import RedactionRect, redact_pdf_by_rectangles
from redactpdf.regex_guard import RegexBudget
from redactpdf.sanitize import sanitize_document, signature_fields
from redactpdf.search import SearchOptions, find_redaction_rectangles


@dataclass(frozen=True)
class RedactionOptions:
    # Mêmes défauts que OptionsModel : sûrs, pas permissifs.
    image_mode: str = "pixels"
    apply_graphics: bool = True
    sanitize_metadata: bool = True
    remove_annotations: bool = True
    remove_attachments: bool = True
    remove_outline: bool = True
    remove_document_actions: bool = True


@dataclass(frozen=True)
class SearchRequest:
    query: str
    case_sensitive: bool = False
    whole_word: bool = False
    ignore_accents: bool = False
    pages: Sequence[int] | None = None


@dataclass(frozen=True)
class RegexRequest:
    patterns: list[str]
    case_sensitive: bool = False
    multiline: bool = False
    ignore_accents: bool = False
    pages: Sequence[int] | None = None


@dataclass(frozen=True)
class PresetsRequest:
    presets: list[str]
    pages: Sequence[int] | None = None


@dataclass(frozen=True)
class PlanResult:
    manual: list[RedactionRect]
    search: list[RedactionRect]
    regex: list[RedactionRect]
    presets: list[RedactionRect]
    full_page: list[RedactionRect]
    all_rects: list[RedactionRect]
    # Ce que l'OCR a proposé. Un compartiment à part, et pas un ajout dans
    # `manual`, parce que la différence est le contrat : ces rectangles sont
    # caviardés comme les autres, mais ils ne sont couverts par aucune garantie
    # et ils ne doivent jamais éteindre un signalement. `drop_covered` ne lit que
    # `manual` et `full_page` ; ranger une proposition ailleurs qu'ici ferait
    # sauter la relecture humaine que le mode `review` existe pour imposer.
    ocr: list[RedactionRect] = field(default_factory=list)


def with_ocr_proposals(plan: PlanResult, proposals: list[RedactionRect]) -> PlanResult:
    """Ajoute les propositions au plan sans les faire passer pour des décisions.

    Elles entrent dans `all_rects`, donc elles sont bien retirées du document, et
    dans `ocr`, donc le rapport peut les nommer. Elles n'entrent nulle part
    ailleurs : ni dans `manual`, ni dans `full_page`, les deux seules listes que
    `drop_covered` consulte.
    """
    if not proposals:
        return plan
    return PlanResult(
        manual=plan.manual,
        search=plan.search,
        regex=plan.regex,
        presets=plan.presets,
        full_page=plan.full_page,
        all_rects=_dedupe_rects(plan.all_rects + proposals),
        ocr=list(proposals),
    )


def _dedupe_rects(rects: list[RedactionRect]) -> list[RedactionRect]:
    seen: set[tuple[int, float, float, float, float]] = set()
    out: list[RedactionRect] = []
    for r in rects:
        k = (int(r.page), round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2))
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def plan_redactions(
    pdf_bytes: bytes,
    *,
    manual_rects: list[RedactionRect] | None = None,
    searches: Sequence[SearchRequest] | None = None,
    regexes: Sequence[RegexRequest] | None = None,
    presets: PresetsRequest | None = None,
    full_page_rects: list[RedactionRect] | None = None,
) -> PlanResult:
    if not pdf_bytes:
        raise ValueError("Empty PDF bytes")

    # Les règles travaillent sur un document dont tous les calques sont allumés.
    # Ce n'est pas une entorse à « les rectangles viennent de l'original » : rien
    # n'est caviardé ici, on rend seulement visible ce que l'original contient
    # déjà. Les coordonnées sont inchangées, et le caviardage s'applique bien
    # aux octets d'origine.
    pdf_bytes = all_layers_visible(pdf_bytes)

    # Un seul budget pour toute la phase : les motifs sont exécutés ligne par
    # ligne et règle par règle, un délai par appel serait multiplié d'autant.
    budget = RegexBudget()

    manual_out = list(manual_rects or [])
    full_page_out = list(full_page_rects or [])

    search_rects: list[RedactionRect] = []
    regex_rects: list[RedactionRect] = []
    presets_rects: list[RedactionRect] = []

    if searches:
        for s in searches:
            search_rects.extend(
                find_redaction_rectangles(
                    pdf_bytes,
                    SearchOptions(
                        query=s.query,
                        case_sensitive=s.case_sensitive,
                        whole_word=s.whole_word,
                        ignore_accents=s.ignore_accents,
                        pages=s.pages,
                    ),
                    budget=budget,
                )
            )

    if regexes:
        for r in regexes:
            regex_rects.extend(
                find_redaction_rectangles_by_regex(
                    pdf_bytes,
                    r.patterns,
                    case_sensitive=r.case_sensitive,
                    pages=r.pages,
                    multiline=r.multiline,
                    ignore_accents=r.ignore_accents,
                    budget=budget,
                )
            )

    if presets is not None:
        presets_rects = find_redaction_rectangles_for_presets(
            pdf_bytes,
            presets.presets,
            pages=presets.pages,
            budget=budget,
        )

    all_rects = _dedupe_rects(manual_out + search_rects + regex_rects + presets_rects)

    return PlanResult(
        manual=manual_out,
        search=search_rects,
        regex=regex_rects,
        presets=presets_rects,
        full_page=full_page_out,
        all_rects=all_rects,
    )


def apply_plan(pdf_bytes: bytes, plan: PlanResult, *, options: RedactionOptions) -> bytes:
    """
    Apply the plan in two passes when full-page rules exist:
      1. Strict pass on full-page rects (remove images + graphics, irrespective
         of the user's chosen image_mode). A page-wide rule is always meant to
         wipe everything.
      2. User-mode pass on every other rect.
    Sanitisation (metadata / annotations / attachments) runs on the final pass.
    """
    if plan.full_page:
        pdf_bytes = redact_pdf_by_rectangles(
            pdf_bytes,
            plan.full_page,
            image_mode="remove",
            apply_graphics=True,
            # Defer sanitisation to the second pass so it's applied once on the final PDF.
            sanitize_metadata=False,
            remove_annotations=False,
            remove_attachments=False,
            remove_outline=False,
            remove_document_actions=False,
        )

    return redact_pdf_by_rectangles(
        pdf_bytes,
        plan.all_rects,
        image_mode=options.image_mode,
        apply_graphics=options.apply_graphics,
        sanitize_metadata=options.sanitize_metadata,
        remove_annotations=options.remove_annotations,
        remove_attachments=options.remove_attachments,
        remove_outline=options.remove_outline,
        remove_document_actions=options.remove_document_actions,
    )


def presets_internal_audit(
    out_pdf: bytes, *, presets: PresetsRequest, budget: RegexBudget | None = None
) -> dict[str, Any] | None:
    """
    Internal presets audit: rerun presets detection on OUT PDF.
    If leaks remain -> return a structured fail report, else None.
    """
    leaks_by_preset: dict[str, list[RedactionRect]] = {}
    total = 0
    matched_pages: set[int] = set()

    for p in presets.presets:
        rects = find_redaction_rectangles_for_presets(
            out_pdf, [p], pages=presets.pages, budget=budget
        )
        leaks_by_preset[p] = rects
        total += len(rects)
        matched_pages.update((r.page + 1) for r in rects)  # 1-based

    if total == 0:
        return None

    matches: list[dict[str, Any]] = []
    doc = pymupdf.open(stream=out_pdf, filetype="pdf")
    try:
        for preset_key, rects in leaks_by_preset.items():
            for r in rects:
                page = doc[r.page]
                rect = pymupdf.Rect(r.x0, r.y0, r.x1, r.y1)
                snippet = (page.get_textbox(rect) or "").strip()
                matches.append(
                    {
                        "preset": preset_key,
                        "page": r.page + 1,
                        "rect": {"x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1},
                        "snippet": snippet,
                    }
                )
    finally:
        doc.close()

    return {
        "status": "fail",
        "total_matches": total,
        "matched_pages": sorted(matched_pages),
        "options": {
            "mode": "presets_internal",
            "pages": list(presets.pages) if presets.pages else None
        },
        "presets": presets.presets,
        "matches": matches,
    }


class PasswordRequired(ValueError):
    """Le document est chiffré et le mot de passe manque ou ne convient pas.

    Sous-classe de `ValueError` pour retomber sur le chemin 400 existant, comme
    `RegexTimeout`. Le code porté par l'instance permet à l'interface de dire
    quoi faire, au lieu d'afficher le message brut de PyMuPDF (« document closed
    or encrypted »), qui n'apprend rien à personne.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def decrypted_view(pdf_bytes: bytes, password: str | None) -> bytes:
    """Le document déchiffré une bonne fois, à l'entrée.

    Tout le reste du traitement ouvre le PDF à plusieurs reprises (plan, zones
    opaques, OCR, audit) : propager un mot de passe dans chacun de ces chemins
    multiplierait les occasions d'en oublier un, et un seul oubli suffirait à
    faire échouer l'export sans que la cause soit lisible. On paie une
    réécriture, et tout l'aval voit un PDF ordinaire.

    Un mot de passe **propriétaire** seul n'empêche pas l'ouverture : ce document
    passe sans rien demander, et c'est le cas courant des PDF « protégés ».
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        if not doc.needs_pass:
            return pdf_bytes
        if not password:
            raise PasswordRequired("password_required")
        if not doc.authenticate(password):
            raise PasswordRequired("password_incorrect")
        return bytes(doc.tobytes())
    finally:
        doc.close()


def signatures_in(pdf_bytes: bytes) -> list[str]:
    """Les champs de signature du document d'entrée, pour pouvoir le dire.

    Aucun caviardage ne préserve une signature : elle couvre les octets du
    fichier et on les réécrit. La question n'est donc pas de la sauver, mais de
    prévenir. Mesuré avant d'ajouter ceci, sur un PDF portant un champ de
    signature et une règle « Dupont » : HTTP 200, le nom retiré, le widget de
    signature retiré, et pas un mot du rapport à ce sujet.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        return signature_fields(doc)
    finally:
        doc.close()


def all_layers_visible(pdf_bytes: bytes) -> bytes:
    """Le document avec tous ses calques allumés, sans autre changement.

    Un PDF peut porter des groupes de contenu optionnel (OCG) éteints par
    défaut. `get_text()` respecte cet état, donc la règle **ne voit rien** :
    mesuré le 9 septembre 2026, un nom posé sur un calque masqué rendait zéro
    rectangle, et seul l'audit à deux moteurs rattrapait, en refusant l'export.

    Refus honnête, mais impasse : l'utilisateur ne peut pas dessiner de rectangle
    sur un texte qu'il ne voit pas. Or ce texte est bien dans le fichier, et
    n'importe quel lecteur rallume le calque d'un clic.

    Allumer un calque ne caviarde rien et ne déplace rien : les coordonnées
    restent celles de l'original, l'invariant du plan est intact. On révèle, on
    ne modifie pas.

    Rend les octets d'origine quand il n'y a pas de calque, ce qui est le cas de
    l'immense majorité des documents : inutile de réécrire un PDF pour rien.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        ocgs = doc.get_ocgs()
        if not ocgs:
            return pdf_bytes
        doc.set_layer(-1, on=list(ocgs.keys()), off=[])
        return bytes(doc.tobytes())
    except Exception:
        # Un document dont on ne sait pas manipuler les calques reste traité tel
        # quel : mieux vaut le contrôle habituel que pas de contrôle du tout.
        return pdf_bytes
    finally:
        doc.close()


def readable_view(pdf_bytes: bytes, options: RedactionOptions) -> bytes:
    """Le document débarrassé de ses porteurs, mais **sans caviardage**.

    C'est là-dessus qu'on demande « qu'est-ce que les règles n'ont pas pu lire »,
    et non sur l'original. Une image qui ne vit que dans l'apparence d'une
    annotation que l'assainissement supprime n'existera pas dans le fichier
    rendu : la faire relire, c'est demander de vérifier quelque chose qu'on est
    en train d'effacer. Mesuré sur une convention de stage réelle, un tampon
    « Draft » ajoutait un cinquième écran de revue pour une image absente de
    l'export, et cette image-là n'était même pas extractible.

    Sans caviardage, en revanche : le plan des rectangles reste calculé sur
    l'original, et une zone déjà noircie ne répondrait plus à la question posée.
    L'assainissement, lui, ne retire que des porteurs hors flux de contenu, donc
    il ne peut pas cacher du texte qu'une règle visait.

    Rend les octets d'origine quand il n'y a rien à retirer : inutile de
    reconstruire un document pour n'en rien changer.
    """
    if not (
        options.sanitize_metadata
        or options.remove_annotations
        or options.remove_attachments
        or options.remove_outline
        or options.remove_document_actions
    ):
        return pdf_bytes

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        sanitize_document(
            doc,
            sanitize_metadata=options.sanitize_metadata,
            remove_annotations=options.remove_annotations,
            remove_attachments=options.remove_attachments,
            remove_outline=options.remove_outline,
            remove_document_actions=options.remove_document_actions,
        )
        return bytes(doc.tobytes(garbage=4, deflate=True))
    except Exception:
        # Un assainissement qui échoue ne doit pas faire disparaître le contrôle :
        # on retombe sur l'original, quitte à signaler une zone de trop.
        return pdf_bytes
    finally:
        doc.close()


def unresolved_opaque_regions(
    pdf_bytes: bytes,
    plan: PlanResult,
    *,
    has_textual_rules: bool,
) -> list[OpaqueRegion]:
    """Zones que les règles textuelles n'ont pas pu lire et que rien ne couvre.

    Calculé sur le PDF **d'origine** : la question est « qu'est-ce que les règles
    pouvaient lire au moment où elles ont travaillé », et une zone déjà caviardée
    n'y répondrait plus. Même invariant que pour les rectangles.

    Sans règle textuelle il n'y a rien à signaler : l'utilisateur n'a jamais
    attendu du moteur qu'il lise quoi que ce soit.
    """
    if not has_textual_rules:
        return []

    regions = find_opaque_regions(pdf_bytes)
    if not regions:
        return []

    # Une zone déjà couverte par une règle géométrique est traitée. C'est ce qui
    # rend le contrôle vivable : le geste naturel devant un signalement, dessiner
    # un rectangle, l'éteint pour de bon.
    covering = [(r.page, (r.x0, r.y0, r.x1, r.y1)) for r in plan.manual + plan.full_page]
    return drop_covered(regions, covering)


def ocr_targets(pdf_bytes: bytes, plan: PlanResult) -> list[OpaqueRegion]:
    """Les images sur lesquelles lancer le détecteur, seuil de revue mis à part.

    Volontairement plus large que `unresolved_opaque_regions` : le seuil de revue
    décide de ce qu'on **montre** à l'utilisateur, pas de ce qu'on lit. Un logo
    sous le seuil ne mérite pas un écran de relecture, mais rien n'empêche d'y
    lire un nom d'employeur au passage, et ça coûte un dixième de seconde.

    Filtré par `drop_covered` comme le reste : inutile de lire sous un rectangle
    qui va tout recouvrir.
    """
    regions = find_opaque_regions(pdf_bytes, min_share=OCR_MIN_PAGE_SHARE)
    if not regions:
        return []
    covering = [(r.page, (r.x0, r.y0, r.x1, r.y1)) for r in plan.manual + plan.full_page]
    return drop_covered(regions, covering)


def unreadable_fonts(
    pdf_bytes: bytes,
    plan: PlanResult,
    *,
    has_textual_rules: bool,
) -> list[UnreliableFont]:
    """Polices dont l'extraction ne rend rien d'exploitable, page par page.

    Même logique que les zones opaques : sans règle textuelle il n'y a rien à
    signaler, et une page entièrement couverte par une règle géométrique est
    traitée. La couverture doit être totale ici : contrairement à une image, on ne
    sait pas *où* est le texte concerné, puisque justement on ne sait pas le lire.
    """
    if not has_textual_rules:
        return []

    fonts = find_unreliable_fonts(pdf_bytes)
    if not fonts:
        return []

    covering = [(r.page, (r.x0, r.y0, r.x1, r.y1)) for r in plan.manual + plan.full_page]
    return drop_fully_covered_pages(fonts, covering, page_rects_of(pdf_bytes))


def _merge_extractors(acc: dict[str, str], report: dict[str, Any]) -> None:
    """Retient l'état de chaque moteur de lecture, la panne l'emportant sur « ok ».

    Sans cela, `extractors` n'apparaîtrait que dans un rapport d'échec, alors que
    c'est sur un succès qu'on a besoin de savoir combien de lecteurs l'ont validé.
    """
    for engine, status in (report.get("extractors") or {}).items():
        if acc.get(engine) in (None, "ok"):
            acc[engine] = status


def audit_plan(
    out_pdf: bytes,
    *,
    searches: Sequence[SearchRequest] | None = None,
    regexes: Sequence[RegexRequest] | None = None,
    presets: PresetsRequest | None = None,
    extra_audit: AuditOptions | None = None,
) -> dict[str, Any]:
    """
    Run coherent audits for all components that were requested.
    Supports multiple search and regex rules.
    """
    # Budget distinct de celui de la planification : l'audit rejoue les mêmes
    # motifs sur le document de sortie, et mérite sa propre enveloppe plutôt que
    # d'hériter d'un budget déjà consommé.
    budget = RegexBudget()

    failures: dict[str, Any] = {}

    # Quels moteurs ont réellement lu la sortie. Un « pass » obtenu avec un

    # seul lecteur ne vaut pas un « pass » obtenu avec deux, et la différence

    # doit rester lisible dans le rapport de succès, pas seulement d'échec.

    extractors: dict[str, str] = {}

    # --- Searches audit (cohérent avec whole_word / case_sensitive), par règle
    if searches:
        failed: list[dict[str, Any]] = []
        for idx, s in enumerate(searches):
            s_opts = build_audit_for_search(
                query=s.query,
                case_sensitive=s.case_sensitive,
                whole_word=s.whole_word,
                ignore_accents=s.ignore_accents,
            )
            report = audit_pdf_text(out_pdf, s_opts, budget=budget)
            _merge_extractors(extractors, report)
            if report["status"] != "pass":
                failed.append(
                    {
                        "index": idx,
                        "query": s.query,
                        "case_sensitive": s.case_sensitive,
                        "whole_word": s.whole_word,
                        "pages": list(s.pages) if s.pages else None,
                        "report": report,
                    }
                )

        if failed:
            failures["searches"] = {
                "status": "fail",
                "rules_failed": len(failed),
                "rules_total": len(list(searches)),
                "failed": failed,
            }

    # --- Regex audit (cohérent : mêmes patterns), par règle
    if regexes:
        failed = []
        for idx, r in enumerate(regexes):
            r_opts = AuditOptions(
                patterns=r.patterns,
                regex=True,
                case_sensitive=r.case_sensitive,
                ignore_accents=r.ignore_accents,
            )
            report = audit_pdf_text(out_pdf, r_opts, budget=budget)
            _merge_extractors(extractors, report)
            if report["status"] != "pass":
                failed.append(
                    {
                        "index": idx,
                        "patterns": r.patterns,
                        "case_sensitive": r.case_sensitive,
                        "multiline": r.multiline,
                        "pages": list(r.pages) if r.pages else None,
                        "report": report,
                    }
                )

        if failed:
            failures["regexes"] = {
                "status": "fail",
                "rules_failed": len(failed),
                "rules_total": len(list(regexes)),
                "failed": failed,
            }

    # --- Presets internal audit
    if presets is not None:
        leak_report = presets_internal_audit(out_pdf, presets=presets, budget=budget)
        if leak_report is not None:
            failures["presets"] = leak_report

    # --- Extra audit (optional banlist)
    if extra_audit is not None:
        report = audit_pdf_text(out_pdf, extra_audit, budget=budget)
        _merge_extractors(extractors, report)
        if report["status"] != "pass":
            failures["audit"] = report

    if failures:
        return {
            "status": "fail",
            "components_failed": sorted(failures.keys()),
            "components": failures,
            "diagnostics": _diagnose(failures),
            "extractors": extractors,
        }

    return {
        "status": "pass",
        "total_matches": 0,
        "matched_pages": [],
        "options": {"mode": "apply_combined"},
        "components": {},
        "extractors": extractors,
    }


# Codes lisibles par machine, traduits par l'interface : le backend ne sait pas
# dans quelle langue s'adresse l'utilisateur, et un rapport en anglais dans une
# UI française est le genre de détail qui fait douter du reste.
DIAGNOSTIC_LINE_BREAK_SPLIT = "line_break_split"


def _diagnose(failures: dict[str, Any]) -> list[str]:
    """Expliquer *pourquoi* un caviardage a échoué, pas seulement qu'il a échoué.

    Sans cela, l'utilisateur reçoit un 400 et un rapport qui dit ce qui a
    survécu, sans rien qui l'oriente vers ce qui débloque. Le seul cas qu'on
    sache diagnostiquer aujourd'hui est celui où la correspondance franchit un
    retour à la ligne : le moteur raisonne par lignes et n'apparie que des
    lignes géométriquement voisines, si bien que deux cellules d'un tableau ou
    deux colonnes ne sont volontairement jamais fusionnées.
    """
    codes: list[str] = []
    for component in failures.values():
        for failed in component.get("failed", []) or []:
            for match in failed.get("report", {}).get("matches", []) or []:
                if match.get("spans_line_break"):
                    codes.append(DIAGNOSTIC_LINE_BREAK_SPLIT)
                    return sorted(set(codes))
    return codes
