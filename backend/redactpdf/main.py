from __future__ import annotations

import base64
import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.responses import Response

from redactpdf.audit import AuditOptions
from redactpdf.heartbeat import heartbeat
from redactpdf.opaque import OpaqueRegion, covered_in_image, region_previews
from redactpdf.paths import frontend_dist
from redactpdf.pipeline import (
    PresetsRequest,
    RedactionOptions,
    RegexRequest,
    SearchRequest,
    apply_plan,
    audit_plan,
    plan_redactions,
    readable_view,
    unreadable_fonts,
    unresolved_opaque_regions,
)
from redactpdf.presets import DEFAULT_REGION, available_presets
from redactpdf.redaction import RedactionRect

app = FastAPI()
router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/config")
def config() -> dict[str, str]:
    """Réglages serveur dont l'UI a besoin pour que son aperçu dise la vérité.

    Le preset téléphone valide ses candidats avec libphonenumber contre une
    région par défaut (`REDACT_DEFAULT_REGION`). Sans connaître la même région,
    l'aperçu surlignerait des numéros que le backend n'ira jamais caviarder --
    un surlignage lu comme une promesse, suivi d'un export réussi qui laisse la
    donnée en clair.
    """
    return {"default_region": DEFAULT_REGION}


@router.post("/heartbeat")
def heartbeat_ping() -> Response:
    """Liveness ping from the desktop UI. Inert unless the app was started via
    launch.py, where the watchdog uses it to auto-stop after the tab closes."""
    heartbeat.touch()
    return Response(status_code=204)


@router.post("/heartbeat/close")
def heartbeat_close() -> Response:
    """Sent by the page (sendBeacon) when the tab is closing, for a prompt
    shutdown in launcher mode; a no-op otherwise."""
    heartbeat.request_close()
    return Response(status_code=204)


# ----------------------------
# Shared helpers
# ----------------------------


def _add_report_headers(headers: dict[str, Any], report: dict[str, Any]) -> None:
    report_json = json.dumps(report, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    b64 = base64.urlsafe_b64encode(report_json).decode("ascii")
    if len(b64) <= 6000:
        headers["X-Redaction-Audit-Report-B64"] = b64
    else:
        headers["X-Redaction-Audit-Report-Truncated"] = "1"


# ----------------------------
# Models
# ----------------------------


class StrictModel(BaseModel):
    """Modèle de payload qui refuse toute clé inconnue.

    Un outil de caviardage ne doit jamais écarter en silence une option qu'il ne
    comprend pas. Sans cela, une faute de frappe sur `image_mode` renvoie un 200
    et un PDF dont l'image d'origine est intacte sous le calque noir, sans qu'un
    seul message ne le signale. La clé inconnue produit désormais un 422 de
    validation qui la nomme.
    """

    model_config = ConfigDict(extra="forbid")


class RectModel(StrictModel):
    page: int = Field(ge=0)
    x0: float
    y0: float
    x1: float
    y1: float


class OptionsModel(StrictModel):
    # "none"   : ne touche pas aux images
    # "remove" : supprime entièrement les images intersectées (mode strict)
    # "pixels" : noircit uniquement la zone intersectée (caviardage partiel)
    # Défauts alignés sur ce que l'UI envoie : un défaut qui ne caviarde pas est
    # un défaut qui fuit. Mieux vaut caviarder trop, quitte à faire refaire une
    # passe à l'utilisateur, que de laisser passer une donnée.
    image_mode: Literal["none", "remove", "pixels"] = "pixels"
    apply_graphics: bool = True

    # Sanitation "anti-fuites hors visuel" : ON par défaut (secure-by-default).
    sanitize_metadata: bool = True
    remove_annotations: bool = True
    remove_attachments: bool = True
    # Porteurs hors flux de contenu : un signet « Dossier Dupont » survivait à une
    # règle « Dupont » avec un export en 200. Mesuré, puis corrigé.
    remove_outline: bool = True
    remove_document_actions: bool = True

    # Que faire d'une zone que les règles textuelles n'ont pas pu lire (une image
    # sans texte par-dessus, typiquement un scan) :
    #   ignore  l'appelant déclare ne pas vouloir de contrôle sur les images
    #   review  défaut : la zone est rapportée, l'export part une fois acquittée
    #   block   non interactif : seule une règle géométrique déverrouille,
    #           l'acquittement ne compte pas. Pour les scripts, qui ne cliquent pas.
    image_regions: Literal["ignore", "review", "block"] = "review"


class AuditModel(StrictModel):
    patterns: list[str] = Field(..., description="List of strings/regex to ban")
    regex: bool = False
    case_sensitive: bool = True

    @field_validator("patterns")
    @classmethod
    def validate_patterns(cls, v: list[str]) -> list[str]:
        cleaned = [p.strip() for p in v if p and p.strip()]
        if not cleaned:
            raise ValueError("audit.patterns must contain at least one non-empty pattern")
        return cleaned


# Ces défauts ne servent qu'aux appelants directs de l'API : l'interface envoie
# toujours ses propres valeurs. C'est ce qui les rend faciles à faire dériver sans
# que personne ne le voie, et l'audit ne rattrape pas la dérive puisqu'il rejoue
# la même option.
#
# La règle n'est pas « caviarder le plus possible » mais « faire ce que la règle
# voulait dire ». Les deux options divergent sur ce point :
#
#   ignore_accents=True -> « Benoit » et « Benoît » sont le même nom, l'accent est
#                          un accident d'encodage. Ne pas le retirer, c'est manquer
#                          ce qui était visé. Le repliage préserve la longueur,
#                          donc la cartographie span -> rectangle reste valide.
#   whole_word=True     -> « cat » et « catch » sont deux mots différents.
#                          Apparier le second, c'est mutiler un tiers : une règle
#                          « Dupont » emportait « Dupontel », le nom de quelqu'un
#                          d'autre, pendant que l'utilisateur croyait n'en viser
#                          qu'un.
#
# Ce que whole_word ne coûte pas : build_whole_word_pattern pose ses frontières
# sur \w, donc « . », « @ », « - » et « ' » restent des séparateurs. « Dupont »
# est toujours trouvé dans « jean.dupont@example.com » et « Dupont-Martin ». Il ne
# manque que la cible collée dans un jeton alphanumérique (« IDDUPONT123 »), forme
# rare pour les données que cet outil vise.
#
# tests/test_api_defaults.py fige les deux, dans les deux sens de dérive.
class SearchOptionsModel(StrictModel):
    case_sensitive: bool = False
    whole_word: bool = True
    ignore_accents: bool = True


class AcknowledgedRegionModel(StrictModel):
    """« J'ai regardé cette zone et je la laisse passer. »"""

    page: int = Field(ge=0)
    bbox: list[float] = Field(min_length=4, max_length=4)


class ScopeModel(StrictModel):
    # None => toutes les pages
    pages: list[int] | None = None

    @field_validator("pages")
    @classmethod
    def validate_pages(cls, v: list[int] | None) -> list[int] | None:
        if v is None or len(v) == 0:
            return None
        if any(p < 0 for p in v):
            raise ValueError("scope.pages must contain only non-negative page indices")
        return v


# ----------------------------
# Endpoint: /redact/apply
# ----------------------------


class ApplySearchModel(StrictModel):
    query: str
    options: SearchOptionsModel = Field(default_factory=SearchOptionsModel)
    scope: ScopeModel = Field(default_factory=ScopeModel)

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("search.query must be non-empty")
        return v.strip()


class ApplyRegexModel(StrictModel):
    patterns: list[str]
    case_sensitive: bool = False
    multiline: bool = False
    # Voir SearchOptionsModel. Pas de `whole_word` ici, et c'est voulu : une regex
    # est un instrument précis, celui qui l'écrit pose ses frontières lui-même.
    ignore_accents: bool = True
    scope: ScopeModel = Field(default_factory=ScopeModel)

    @field_validator("patterns", mode="before")
    @classmethod
    def coerce_patterns(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ValueError("regex.patterns must be non-empty")
            return [s]
        if isinstance(v, list):
            cleaned = [str(p).strip() for p in v if p and str(p).strip()]
            if not cleaned:
                raise ValueError("regex.patterns must be non-empty")
            return cleaned
        raise ValueError("regex.patterns must be non-empty")


class ApplyPresetsModel(StrictModel):
    presets: list[str]
    scope: ScopeModel = Field(default_factory=ScopeModel)

    @field_validator("presets")
    @classmethod
    def validate_presets(cls, v: list[str]) -> list[str]:
        cleaned = [p.strip() for p in v if p and p.strip()]
        if not cleaned:
            raise ValueError("presets.presets must contain at least one non-empty preset key")

        allowed = set(available_presets())
        unknown = [p for p in cleaned if p not in allowed]
        if unknown:
            raise ValueError(
                f"Unknown preset(s): {', '.join(unknown)}. Available: {', '.join(sorted(allowed))}"
            )
        return cleaned


class ApplyPayload(StrictModel):
    rects: list[RectModel] = Field(default_factory=list)
    # Page-wide rules. Always processed in strict mode (full image + graphics
    # removal) regardless of options.image_mode, a page-wide rule is meant
    # to wipe the page completely.
    full_page_rects: list[RectModel] = Field(default_factory=list)

    # Compat existante (single)
    search: ApplySearchModel | None = None
    regex: ApplyRegexModel | None = None

    # NOUVEAU : multi-règles
    searches: list[ApplySearchModel] = Field(default_factory=list)
    regexes: list[ApplyRegexModel] = Field(default_factory=list)

    presets: ApplyPresetsModel | None = None
    options: OptionsModel = Field(default_factory=OptionsModel)
    audit: AuditModel | None = None

    # L'acquittement voyage dans la requête et le serveur recalcule les zones pour
    # le vérifier. Laissé au client, il suffirait de ne rien envoyer.
    acknowledged_regions: list[AcknowledgedRegionModel] = Field(default_factory=list)

    # Pour une police illisible on ne sait pas *où* est le texte concerné, donc
    # l'acquittement porte sur la page entière et non sur une boîte.
    acknowledged_font_pages: list[int] = Field(default_factory=list)


# Tolérance d'appariement entre une zone rapportée et son acquittement. Le client
# renvoie la boîte telle qu'on la lui a donnée, arrondie au centième : un point
# de marge suffit et évite qu'un arrondi fasse échouer un acquittement légitime.
_ACK_TOLERANCE_PT = 1.0


def _is_acknowledged(region: OpaqueRegion, acks: list[AcknowledgedRegionModel]) -> bool:
    x0, y0, x1, y1 = region.bbox
    for ack in acks:
        if ack.page != region.page:
            continue
        a0, b0, a1, b1 = ack.bbox
        if (
            abs(a0 - x0) <= _ACK_TOLERANCE_PT
            and abs(b0 - y0) <= _ACK_TOLERANCE_PT
            and abs(a1 - x1) <= _ACK_TOLERANCE_PT
            and abs(b1 - y1) <= _ACK_TOLERANCE_PT
        ):
            return True
    return False


@router.post("/redact/apply")
async def redact_apply(
    file: Annotated[UploadFile, File(...)],
    payload: Annotated[str, Form(...)],
) -> Response:
    try:
        data = ApplyPayload.model_validate_json(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload JSON") from None

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty PDF upload")

    manual_rects = [
        RedactionRect(page=r.page, x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1) for r in data.rects
    ]
    full_page_rects = [
        RedactionRect(page=r.page, x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1)
        for r in data.full_page_rects
    ]

    # ----------------------------
    # Build searches list (compat: data.search + data.searches)
    # ----------------------------
    search_models: list[ApplySearchModel] = []
    search_models.extend(list(data.searches or []))
    if data.search is not None:
        search_models.append(data.search)

    searches_req: list[SearchRequest] = []
    for s in search_models:
        searches_req.append(
            SearchRequest(
                query=s.query,
                case_sensitive=s.options.case_sensitive,
                whole_word=s.options.whole_word,
                ignore_accents=s.options.ignore_accents,
                pages=s.scope.pages,
            )
        )

    # ----------------------------
    # Build regexes list (compat: data.regex + data.regexes)
    # ----------------------------
    regex_models: list[ApplyRegexModel] = []
    regex_models.extend(list(data.regexes or []))
    if data.regex is not None:
        regex_models.append(data.regex)

    regexes_req: list[RegexRequest] = []
    for r in regex_models:
        regexes_req.append(
            RegexRequest(
                patterns=r.patterns,
                case_sensitive=r.case_sensitive,
                multiline=r.multiline,
                ignore_accents=r.ignore_accents,
                pages=r.scope.pages,
            )
        )

    # ----------------------------
    # Presets (unchanged)
    # ----------------------------
    presets_req: PresetsRequest | None = None
    if data.presets is not None:
        presets_req = PresetsRequest(
            presets=data.presets.presets,
            pages=data.presets.scope.pages,
        )

    # Une seule construction : la vue sur laquelle on juge « qu'est-ce qui n'a pas
    # pu être lu » et le document produit doivent parler du même assainissement.
    redaction_options = RedactionOptions(
        image_mode=data.options.image_mode,
        apply_graphics=data.options.apply_graphics,
        sanitize_metadata=data.options.sanitize_metadata,
        remove_annotations=data.options.remove_annotations,
        remove_attachments=data.options.remove_attachments,
        remove_outline=data.options.remove_outline,
        remove_document_actions=data.options.remove_document_actions,
    )

    try:
        plan = plan_redactions(
            pdf_bytes,
            manual_rects=manual_rects,
            searches=searches_req or None,
            regexes=regexes_req or None,
            presets=presets_req,
            full_page_rects=full_page_rects or None,
        )

        # Avant d'appliquer : y a-t-il une zone que les règles textuelles n'ont pas
        # pu lire ? Mesuré le 9 sept. 2026, un scan sans couche texte renvoyait 200
        # avec la donnée lisible à l'oeil. On refuse plutôt que de rendre un fichier
        # dont on ne peut pas répondre, et on le fait ici pour ne pas gaspiller le
        # travail de caviardage sur une requête qui sera refusée.
        mode = data.options.image_regions
        if mode != "ignore":
            # La question porte sur le document **tel qu'il sortira**, porteurs
            # retirés : une image qui ne vit que dans l'apparence d'une annotation
            # supprimée n'existera pas dans l'export, et la faire relire revient à
            # faire vérifier ce qu'on efface. Sans caviardage en revanche, sinon
            # une zone déjà noircie ne répondrait plus à la question.
            view = readable_view(pdf_bytes, redaction_options)
            unresolved = unresolved_opaque_regions(
                view,
                plan,
                has_textual_rules=bool(searches_req or regexes_req or presets_req),
            )
            fonts = unreadable_fonts(
                view,
                plan,
                has_textual_rules=bool(searches_req or regexes_req or presets_req),
            )
            if mode == "review":
                unresolved = [
                    r for r in unresolved if not _is_acknowledged(r, data.acknowledged_regions)
                ]
                acked_pages = set(data.acknowledged_font_pages)
                fonts = [f for f in fonts if f.page not in acked_pages]
            if unresolved or fonts:
                # Ce que l'humain doit regarder voyage avec le refus : les pixels
                # de l'image seule (pas la région de page, qui composerait par
                # dessus la couche texte que les règles ont justement su lire), et
                # ce qui y est déjà couvert, exprimé dans le repère de l'image.
                covering = [
                    (r.page, (r.x0, r.y0, r.x1, r.y1)) for r in plan.manual + plan.full_page
                ]
                regions_out: list[dict[str, object]] = []
                for region in unresolved:
                    entry = region.as_dict()
                    entry["covered"] = covered_in_image(region, covering)
                    regions_out.append(entry)
                raise HTTPException(
                    status_code=409,
                    detail={
                        "status": "inconclusive",
                        "mode": mode,
                        "opaque_regions": regions_out,
                        "unreliable_fonts": [f.as_dict() for f in fonts],
                        "previews": region_previews(view, unresolved),
                    },
                )

        out_pdf = apply_plan(pdf_bytes, plan, options=redaction_options)
    except HTTPException:
        # Le refus pour zone non résolue est une réponse construite, pas une panne :
        # sans cette clause, le filet à 500 ci-dessous l'avalait.
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Redaction failed") from e

    extra_audit: AuditOptions | None = None
    if data.audit is not None:
        extra_audit = AuditOptions(
            patterns=data.audit.patterns,
            regex=data.audit.regex,
            case_sensitive=data.audit.case_sensitive,
        )

    try:
        composite = audit_plan(
            out_pdf,
            searches=searches_req or None,
            regexes=regexes_req or None,
            presets=presets_req,
            extra_audit=extra_audit,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"status": "error", "error": str(e)})

    if composite.get("status") != "pass":
        return JSONResponse(status_code=400, content=composite)

    headers: dict[str, Any] = {
        "Content-Disposition": 'attachment; filename="redacted.pdf"',
        "X-Redaction-Audit-Status": "pass",
        "X-Redaction-Audit-Matches": "0",
        "X-Redaction-Manual-Occurrences": str(len(plan.manual)),
        "X-Redaction-Search-Occurrences": str(len(plan.search)),
        "X-Redaction-Regex-Occurrences": str(len(plan.regex)),
        "X-Redaction-Presets-Occurrences": str(len(plan.presets)),
        "X-Redaction-Full-Page-Occurrences": str(len(plan.full_page)),
        "X-Redaction-Total-Occurrences": str(len(plan.all_rects) + len(plan.full_page)),
    }
    _add_report_headers(headers, composite)
    return Response(content=out_pdf, media_type="application/pdf", headers=headers)


# Expose the API both bare (/redact/apply -- tests + Vite dev proxy) and under
# /api (same-origin production / desktop launcher). Including the router twice
# avoids touching the tests, api.ts or vite.config.ts.
app.include_router(router)
app.include_router(router, prefix="/api")

# Serve the built frontend (same-origin) when it exists, so one process can host
# UI + API (desktop launcher / production). Mounted AFTER the API routes so it
# never shadows them; skipped in dev, where Vite serves the UI and dist is absent.
_FRONTEND_DIST = frontend_dist()
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
