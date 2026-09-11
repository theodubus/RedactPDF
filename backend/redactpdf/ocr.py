"""Proposer des zones dans les images, sans jamais rien garantir.

Ce module est le seul du paquet dont la sortie n'est **pas** couverte par le
contrat. Tout le reste répond « ce que le moteur déterministe a su lire, il l'a
retiré ». L'OCR, lui, est un détecteur approximatif : il lit parfois mal, il rate
parfois tout, et rien dans la sortie ne permet de savoir lequel des deux vient de
se produire. Il ne peut donc pas entrer dans la garantie, et il n'y entre pas.

Ce qu'il fait
-------------
Il donne une couche texte aux zones que les règles n'ont pas pu lire, puis y
lance **les mêmes règles**, sans en réécrire une seule. C'est le point de
conception qui compte : un second moteur d'appariement dériverait du premier, et
« caviarde `Dupont` » ne voudrait plus dire la même chose selon que le nom est
dans le texte ou dans une image. Les rectangles obtenus reviennent au repère de
la page par l'inverse de la matrice de placement, celle-là même qui sert déjà à
situer les zones déjà couvertes.

Ce qu'il ne fait pas
--------------------
Une proposition n'éteint jamais un signalement. Elle ne nourrit pas
`drop_covered`, et c'est une invariante, pas un détail d'implémentation : sinon
un détecteur approximatif suffirait à faire disparaître l'écran de revue, et la
validation humaine que le mode `review` existe pour imposer sauterait toute
seule. `block` n'est pas déverrouillé non plus : une zone parcourue par un
détecteur approximatif n'est pas une zone lue.

L'audit ne change pas davantage. Il relit le texte de la sortie ; ce qu'un OCR a
trouvé dans une image n'y a jamais été, donc il ne peut ni le confirmer ni
l'infirmer. Le rapport le dit.

Empaquetage
-----------
**Rien à installer.** Le moteur voyage déjà dans le `_mupdf.so` de PyMuPDF, ce
qui a été vérifié en masquant entièrement `/usr/bin/tesseract` et
`/usr/share/tesseract-ocr` puis en regardant l'OCR fonctionner depuis une wheel
installée à neuf. Seuls manquaient les modèles de langue : `fra` et `eng`
tiennent dans `redactpdf/_tessdata`, 5 Mo, trouvés par `paths.bundled_tessdata()`.
Un tesseract système sert de repli, jamais de préférence, puisque les chiffres de
qualité cités ici ne valent que pour la variante `tessdata_fast` embarquée.

Une version antérieure de ce module concluait ici l'inverse, « dépendance native
de l'ordre de 22 Mo, ne jamais l'embarquer ». **Cette mesure était fausse** : elle
portait sur le paquet système Ubuntu, qui contient un moteur déjà présent chez
nous. Le coût réel était de 5 Mo, et l'arbitrage a été renversé le 9 septembre
2026.
"""
from __future__ import annotations

import pathlib
from collections.abc import Sequence
from dataclasses import dataclass

import pymupdf

from redactpdf.opaque import MIN_PAGE_SHARE, OpaqueRegion
from redactpdf.paths import bundled_tessdata
from redactpdf.presets import find_redaction_rectangles_for_presets
from redactpdf.redaction import RedactionRect
from redactpdf.regex_guard import RegexBudget
from redactpdf.search import SearchOptions, find_redaction_rectangles

# Défaut mesuré, pas supposé. Le modèle français **seul** lit « BULLE CUT » là où
# le couple lit « BULLETIN CUMULATIF », sur un titre pourtant français : le
# détecteur travaille sur des formes, et deux modèles votent mieux qu'un. Coût
# constaté 1,25 s contre 0,91 s, soit un tiers de plus pour des mots trouvés que
# le français seul ratait.
#
# Testé aussi `tessdata_best` : aucun mot de plus, 4,92 s au lieu de 1,21 s et
# 19 Mo au lieu de 5. Écarté.
DEFAULT_LANGUAGE = "fra+eng"
FALLBACK_LANGUAGE = "eng"

# Le détecteur passe sur **toutes** les images. Ce fut longtemps un seuil
# distinct de celui de la revue, sur l'idée que « peut-on lire quelque chose
# dedans » et « faut-il le signaler » n'appelaient pas la même réponse. Mesuré le
# 10 septembre 2026, cette distinction était intenable : elle laissait un tampon
# à 0,467 % de la page, portant un nom que l'OCR lit mot pour mot, sortir en
# HTTP 200 avec un audit `pass` et aucune revue. Ce qui vaut la peine d'être lu
# vaut la peine d'être dit, donc les deux seuils n'en font plus qu'un et
# `MIN_PAGE_SHARE` est la seule valeur. Voir son commentaire dans `opaque.py`.
#
# Un plancher subsiste quand même : une image d'un pixel ne porte rien, et lancer
# un OCR dessus n'est pas gratuit, seulement bon marché. Mesuré : le logo d'une
# fiche de paie, 202 x 122 pixels, coûte 0,11 s et rend « Liberté Egalité
# Fraternité REPUBLIQUE FRANCAISE ».
OCR_MIN_PAGE_SHARE = MIN_PAGE_SHARE


@dataclass(frozen=True)
class OcrProposal:
    """Un rectangle proposé par l'OCR, en coordonnées de page.

    `text` et `rule` existent pour le rapport : l'utilisateur doit pouvoir lire
    ce que le détecteur a cru voir et quelle règle s'y est appliquée, sinon la
    proposition est une boîte noire qui demande d'être crue sur parole.
    """

    page: int
    bbox: tuple[float, float, float, float]
    rule: str

    def as_dict(self) -> dict[str, object]:
        return {
            "page": self.page,
            "bbox": [round(v, 2) for v in self.bbox],
            "rule": self.rule,
        }

    def as_rect(self) -> RedactionRect:
        return RedactionRect(
            page=self.page,
            x0=self.bbox[0],
            y0=self.bbox[1],
            x1=self.bbox[2],
            y1=self.bbox[3],
        )


def tessdata_dir() -> str | None:
    """Le répertoire de modèles à utiliser, embarqué de préférence.

    L'embarqué passe devant le système : c'est celui dont on connaît la variante
    et l'empreinte, donc le seul sur lequel les mesures de qualité citées plus
    haut valent quelque chose. Le système reste en repli, pour la machine qui a
    déjà une langue qu'on n'embarque pas.
    """
    bundled = bundled_tessdata()
    if bundled is not None:
        return str(bundled)
    try:
        found = pymupdf.get_tessdata()
    except Exception:
        return None
    return str(found) if found else None


def available_languages() -> list[str]:
    """Les langues effectivement utilisables, vide s'il n'y en a aucune."""
    directory = tessdata_dir()
    if not directory:
        return []
    try:
        return sorted(p.stem for p in pathlib.Path(directory).glob("*.traineddata"))
    except OSError:
        return []


def is_available() -> bool:
    """Vrai si un tesseract exploitable est installé sur la machine.

    Appelé aussi par `/api/config`, pour que l'interface puisse griser la case
    plutôt que de proposer une fonction qui échouerait à l'export.
    """
    return bool(available_languages())


def resolve_language(requested: str | None) -> str | None:
    """La langue à utiliser, ou None si aucune n'est utilisable.

    Tesseract accepte plusieurs modèles séparés par `+`, et c'est le défaut ici.
    On filtre sur ce qui est réellement présent : demander une langue absente
    fait échouer la reconnaissance entière, y compris pour les langues qui, elles,
    étaient là.
    """
    langs = set(available_languages())
    if not langs:
        return None
    for candidate in (requested, DEFAULT_LANGUAGE, FALLBACK_LANGUAGE):
        if not candidate:
            continue
        kept = [part for part in candidate.split("+") if part in langs]
        if kept:
            return "+".join(kept)
    return sorted(langs)[0]


# Une page vaut un OCR de son rendu s'il y reste de l'encre une fois le texte
# retiré. Mesuré : une page de texte ordinaire tombe à 0,00 %, la page du piège
# au motif à 0,09 %. Le seuil ne sert qu'à éviter de payer un OCR pour rien, il
# ne décide de rien : une page de tableau le franchit aussi, et l'OCR n'y trouve
# simplement rien, ce qui est correct.
PAGE_MARK_MIN_INK = 0.0002

# Résolution du pré-contrôle. 36 dpi coûtait 3 ms par page mais faisait
# disparaître les traits fins : un texte détouré en contour de 0,4 pt y tombait à
# 0,014 %, sous le seuil, donc jamais lu. À 72 dpi le même texte donne 0,25 %,
# pour 7 ms par page, soit moins d'une seconde sur cent pages. Le filtre ne sert
# qu'à éviter des OCR inutiles ; le rendre myope pour gagner 4 ms serait un
# mauvais échange.
PAGE_MARK_PROBE_DPI = 72

# Résolution du rendu. Assez pour lire un nom, pas plus : le coût de l'OCR suit
# le nombre de pixels, et on paie ici par page et non par image.
PAGE_MARK_DPI = 200


def pages_with_unreported_marks(pdf_bytes: bytes) -> list[int]:
    """Pages qui peignent quelque chose que l'extracteur ne rapporte pas.

    Le vrai trou n'est pas « le vectoriel » mais toute marque visible absente de
    la couche texte : texte converti en courbes, étiquettes d'un graphique, et
    texte peint à travers un motif de tuilage. Mesuré sur ce dernier : le nom est
    parfaitement lisible à l'écran, `get_text()` ne le rapporte pas, la règle
    rend zéro occurrence et l'export part en 200.

    Deux autres pistes de détection ont été mesurées et écartées.
    `get_drawings()` rend **zéro dessin** sur la page du motif, donc compter les
    objets vectoriels y est aveugle. Et la quantité d'encre ne sépare rien : le
    motif en produit 0,09 % quand un tableau parfaitement légitime en produit
    2,65 %. Il ne reste que le rendu, puis un OCR.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    stripped = _strip_marks_only(doc)
    try:
        if stripped is None:
            return []
        out: list[int] = []
        for index in range(stripped.page_count):
            page = stripped.load_page(index)
            pix = page.get_pixmap(dpi=PAGE_MARK_PROBE_DPI, colorspace=pymupdf.csGRAY)
            data = pix.samples
            if not data:
                continue
            dark = sum(1 for value in data if value < 200)
            if dark / len(data) >= PAGE_MARK_MIN_INK:
                out.append(index)
        return out
    finally:
        if stripped is not None:
            stripped.close()
        doc.close()


def _strip_marks_only(doc: pymupdf.Document) -> pymupdf.Document | None:
    """Une copie sans texte **ni images** : il ne reste que les autres marques.

    Les images ont déjà leur propre chemin, celui des zones opaques, qui les
    montre à l'humain. Les garder ici ferait payer un OCR deux fois pour le même
    contenu et signalerait des pages qui sont déjà traitées.
    """
    try:
        copy = pymupdf.open("pdf", doc.tobytes())
        for page in copy:
            page.add_redact_annot(page.rect)
            page.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_REMOVE,
                graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                text=pymupdf.PDF_REDACT_TEXT_REMOVE,
            )
        return copy
    except Exception:
        return None


def _page_from_unit(
    transform: tuple[float, float, float, float, float, float], x: float, y: float
) -> tuple[float, float]:
    a, b, c, d, e, f = transform
    return (a * x + c * y + e, b * x + d * y + f)


def _to_page_rect(
    region: OpaqueRegion, rect: RedactionRect, width: float, height: float
) -> tuple[float, float, float, float]:
    """Un rectangle du mini-PDF ramené sur la page qui porte l'image.

    Passe par la matrice de placement complète, et prend l'enveloppe des quatre
    coins : sur une image posée tournée, la boîte alignée aux axes du mini-PDF
    ne l'est plus une fois sur la page.
    """
    corners = [
        _page_from_unit(region.transform, x / width, y / height)
        for x, y in (
            (rect.x0, rect.y0),
            (rect.x1, rect.y0),
            (rect.x0, rect.y1),
            (rect.x1, rect.y1),
        )
    ]
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _ocr_region(doc: pymupdf.Document, region: OpaqueRegion, language: str) -> bytes | None:
    """Les pixels de la zone, rendus en mini-PDF porteur d'une couche texte OCR.

    Un vrai PDF, et pas une liste de mots, parce que c'est ce qui permet de lui
    appliquer les règles existantes telles quelles.
    """
    if not region.xref:
        # Image en ligne ou apparence d'annotation : pas d'objet à extraire. On
        # ne rend pas la région à la place, ce qui ferait passer du texte de page
        # pour du texte d'image et donnerait une proposition sur du déjà lu.
        return None
    try:
        pix = pymupdf.Pixmap(doc, region.xref)
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        # `bytes(...)` n'est pas décoratif, et `pix` doit rester vivant jusque-là :
        # le tampon rendu est adossé au Pixmap, et le laisser mourir dans
        # l'expression rend un PDF tronqué. Mesuré : 124 caractères lus au lieu
        # de 342, sans la moindre erreur levée.
        return bytes(pix.pdfocr_tobytes(language=language, tessdata=tessdata_dir()))
    except Exception:
        return None


def propose_from_page_marks(
    pdf_bytes: bytes,
    pages: Sequence[int],
    *,
    searches: Sequence[SearchOptions] = (),
    regex_patterns: Sequence[tuple[list[str], bool, bool, bool]] = (),
    presets: Sequence[str] = (),
    language: str | None = None,
    budget: RegexBudget | None = None,
) -> list[OcrProposal]:
    """Ce que les règles trouvent dans un **rendu** de page privé de sa couche texte.

    Même principe que `propose_from_regions`, et surtout les mêmes fonctions de
    règle : le mini-PDF produit par l'OCR est un PDF comme un autre. Ce qui change
    est la source des pixels, une page rendue plutôt qu'une image extraite, et
    c'est ce qui atteint le texte converti en courbes, les étiquettes d'un
    graphique vectoriel et le texte peint par un motif.

    Le texte est retiré du rendu, sinon l'OCR proposerait à nouveau ce que les
    règles ont déjà lu, en moins bien. Les images aussi, elles ont leur propre
    chemin.

    La garantie ne bouge pas d'un pouce : ce sont des propositions, l'audit ne
    les couvre pas, et elles n'éteignent aucun signalement.
    """
    from redactpdf.multiline_regex_engine import find_redaction_rectangles_by_regex

    lang = resolve_language(language)
    if lang is None or not pages:
        return []
    if not (searches or regex_patterns or presets):
        return []

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    stripped = _strip_marks_only(doc)
    out: list[OcrProposal] = []
    try:
        if stripped is None:
            return []
        for index in pages:
            if not 0 <= index < stripped.page_count:
                continue
            page = stripped.load_page(index)
            box = page.rect
            pix = page.get_pixmap(dpi=PAGE_MARK_DPI)
            if pix.alpha:
                pix = pymupdf.Pixmap(pix, 0)
            try:
                mini_bytes = bytes(pix.pdfocr_tobytes(language=lang, tessdata=tessdata_dir()))
            except Exception:
                continue
            mini = pymupdf.open(stream=mini_bytes, filetype="pdf")
            try:
                if mini.page_count == 0:
                    continue
                mini_box = mini.load_page(0).rect
                if mini_box.width <= 0 or mini_box.height <= 0:
                    continue
                # Un rendu de page pleine : le retour au repère de la page est une
                # simple mise à l'échelle, pas une matrice de placement.
                sx = box.width / mini_box.width
                sy = box.height / mini_box.height
                for label, rect in _rules_on(
                    mini_bytes,
                    searches=searches,
                    regex_patterns=regex_patterns,
                    presets=presets,
                    budget=budget,
                    find_by_regex=find_redaction_rectangles_by_regex,
                ):
                    out.append(
                        OcrProposal(
                            page=index,
                            bbox=(
                                box.x0 + rect.x0 * sx,
                                box.y0 + rect.y0 * sy,
                                box.x0 + rect.x1 * sx,
                                box.y0 + rect.y1 * sy,
                            ),
                            rule=label,
                        )
                    )
            finally:
                mini.close()
        return out
    finally:
        if stripped is not None:
            stripped.close()
        doc.close()


def _rules_on(
    mini_bytes: bytes,
    *,
    searches: Sequence[SearchOptions],
    regex_patterns: Sequence[tuple[list[str], bool, bool, bool]],
    presets: Sequence[str],
    budget: RegexBudget | None,
    find_by_regex: object,
) -> list[tuple[str, RedactionRect]]:
    """Les règles de l'utilisateur, appliquées telles quelles au mini-PDF de l'OCR.

    Extraite pour que les deux sources de pixels, image extraite et page rendue,
    passent par exactement le même appariement. Une seconde copie dériverait, et
    « caviarder Dupont » ne voudrait plus dire la même chose selon d'où viennent
    les pixels.
    """
    found: list[tuple[str, RedactionRect]] = []
    for opts in searches:
        for rect in find_redaction_rectangles(mini_bytes, opts, budget=budget):
            found.append((f"search:{opts.query}", rect))
    for patterns, case_sensitive, multiline, ignore_accents in regex_patterns:
        label = f"regex:{patterns[0] if patterns else ''}"
        for rect in find_by_regex(  # type: ignore[operator]
            mini_bytes,
            patterns,
            case_sensitive=case_sensitive,
            multiline=multiline,
            ignore_accents=ignore_accents,
            budget=budget,
        ):
            found.append((label, rect))
    if presets:
        for rect in find_redaction_rectangles_for_presets(
            mini_bytes, list(presets), budget=budget
        ):
            found.append(("preset", rect))
    return found


def propose_from_regions(
    pdf_bytes: bytes,
    regions: Sequence[OpaqueRegion],
    *,
    searches: Sequence[SearchOptions] = (),
    regex_patterns: Sequence[tuple[list[str], bool, bool, bool]] = (),
    presets: Sequence[str] = (),
    language: str | None = None,
    budget: RegexBudget | None = None,
) -> list[OcrProposal]:
    """Les zones que les règles trouvent **dans la couche OCR** des images.

    Aucune règle n'est réécrite ici : le mini-PDF produit par l'OCR est un PDF
    comme un autre, et il passe par les mêmes fonctions que le document. C'est ce
    qui garantit que « caviarder Dupont » veut dire la même chose des deux côtés.
    """
    from redactpdf.multiline_regex_engine import find_redaction_rectangles_by_regex

    lang = resolve_language(language)
    if lang is None or not regions:
        return []
    if not (searches or regex_patterns or presets):
        return []

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    out: list[OcrProposal] = []
    try:
        for region in regions:
            mini_bytes = _ocr_region(doc, region, lang)
            if not mini_bytes:
                continue
            mini = pymupdf.open(stream=mini_bytes, filetype="pdf")
            try:
                if mini.page_count == 0:
                    continue
                box = mini.load_page(0).rect
                width, height = float(box.width), float(box.height)
                if width <= 0 or height <= 0:
                    continue

                found = _rules_on(
                    mini_bytes,
                    searches=searches,
                    regex_patterns=regex_patterns,
                    presets=presets,
                    budget=budget,
                    find_by_regex=find_redaction_rectangles_by_regex,
                )

                for label, rect in found:
                    out.append(
                        OcrProposal(
                            page=region.page,
                            bbox=_to_page_rect(region, rect, width, height),
                            rule=label,
                        )
                    )
            finally:
                mini.close()
        return out
    finally:
        doc.close()
