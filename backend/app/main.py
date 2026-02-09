from __future__ import annotations

import base64
import json
from typing import Annotated, Any

import pymupdf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError, field_validator
from starlette.responses import Response

from app.audit import AuditOptions, audit_pdf_text, build_audit_for_search
from app.multiline_regex_engine import find_redaction_rectangles_by_regex
from app.pipeline import (
    PresetsRequest,
    RedactionOptions,
    RegexRequest,
    SearchRequest,
    apply_plan,
    audit_plan,
    plan_redactions,
)
from app.presets import available_presets, find_redaction_rectangles_for_presets
from app.redaction import RedactionRect, redact_pdf_by_rectangles
from app.search import SearchOptions, find_redaction_rectangles

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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


class RectModel(BaseModel):
    page: int = Field(ge=0)
    x0: float
    y0: float
    x1: float
    y1: float


class OptionsModel(BaseModel):
    apply_images: bool = False
    apply_graphics: bool = False

    # Étape 09 : sanitation "anti-fuites hors visuel"
    sanitize_metadata: bool = False
    remove_annotations: bool = False
    remove_attachments: bool = False


class AuditModel(BaseModel):
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


class RectanglesPayload(BaseModel):
    rects: list[RectModel]
    options: OptionsModel = Field(default_factory=OptionsModel)
    audit: AuditModel


class SearchOptionsModel(BaseModel):
    case_sensitive: bool = False
    whole_word: bool = False


class ScopeModel(BaseModel):
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


class SearchPayload(BaseModel):
    query: str
    options: SearchOptionsModel = Field(default_factory=SearchOptionsModel)
    scope: ScopeModel = Field(default_factory=ScopeModel)
    # options de redaction (images/graphics + sanitize)
    apply: OptionsModel = Field(default_factory=OptionsModel)
    audit: AuditModel

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("query must be non-empty")
        return v.strip()


class PresetsPayload(BaseModel):
    presets: list[str]
    scope: ScopeModel = Field(default_factory=ScopeModel)
    options: OptionsModel = Field(default_factory=OptionsModel)
    # audit optionnel : le backend fait un audit interne cohérent presets
    audit: AuditModel | None = None

    @field_validator("presets")
    @classmethod
    def validate_presets(cls, v: list[str]) -> list[str]:
        cleaned = [p.strip() for p in v if p and p.strip()]
        if not cleaned:
            raise ValueError("presets must contain at least one non-empty preset key")

        allowed = set(available_presets())
        unknown = [p for p in cleaned if p not in allowed]
        if unknown:
            raise ValueError(
                f"Unknown preset(s): {', '.join(unknown)}. Available: {', '.join(sorted(allowed))}"
            )
        return cleaned


class RegexPayload(BaseModel):
    patterns: list[str]
    case_sensitive: bool = False
    multiline: bool = False
    scope: ScopeModel = Field(default_factory=ScopeModel)
    options: OptionsModel = Field(default_factory=OptionsModel)
    audit: AuditModel

    @field_validator("patterns", mode="before")
    @classmethod
    def coerce_patterns(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("patterns must be a non-empty string or a non-empty list")
            return [cleaned]

        if isinstance(v, list):
            cleaned_list = [str(p).strip() for p in v if p and str(p).strip()]
            if not cleaned_list:
                raise ValueError("patterns must be a non-empty string or a non-empty list")
            return cleaned_list

        raise ValueError("patterns must be a non-empty string or a non-empty list")


# ----------------------------
# Endpoints
# ----------------------------


@app.post("/redact/rectangles")
async def redact_rectangles(
    file: Annotated[UploadFile, File(...)],
    payload: Annotated[str, Form(...)],
) -> Response:
    try:
        data = RectanglesPayload.model_validate_json(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload JSON") from None

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty PDF upload")

    rects = [RedactionRect(page=r.page, x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1) for r in data.rects]

    try:
        out_pdf = redact_pdf_by_rectangles(
            pdf_bytes,
            rects,
            apply_images=data.options.apply_images,
            apply_graphics=data.options.apply_graphics,
            sanitize_metadata=data.options.sanitize_metadata,
            remove_annotations=data.options.remove_annotations,
            remove_attachments=data.options.remove_attachments,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Redaction failed") from e

    try:
        report = audit_pdf_text(
            out_pdf,
            AuditOptions(
                patterns=data.audit.patterns,
                regex=data.audit.regex,
                case_sensitive=data.audit.case_sensitive,
            ),
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"status": "error", "error": str(e)})

    if report["status"] != "pass":
        return JSONResponse(status_code=400, content=report)

    headers: dict[str, Any] = {
        "Content-Disposition": 'attachment; filename="redacted.pdf"',
        "X-Redaction-Audit-Status": "pass",
        "X-Redaction-Audit-Matches": "0",
    }
    _add_report_headers(headers, report)
    return Response(content=out_pdf, media_type="application/pdf", headers=headers)


@app.post("/redact/search")
async def redact_search(
    file: Annotated[UploadFile, File(...)],
    payload: Annotated[str, Form(...)],
) -> Response:
    """
    IMPORTANT:
    - L'audit "interne" est construit automatiquement à partir de
      (query, whole_word, case_sensitive) pour éviter les incohérences
      qui causent des faux échecs.
    - L'audit fourni par le client est ensuite exécuté en audit additionnel (banlist),
      sans jamais remplacer l'audit interne.
    """
    try:
        data = SearchPayload.model_validate_json(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload JSON") from None

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty PDF upload")

    try:
        found_rects = find_redaction_rectangles(
            pdf_bytes,
            SearchOptions(
                query=data.query,
                case_sensitive=data.options.case_sensitive,
                whole_word=data.options.whole_word,
                pages=data.scope.pages,
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Search failed") from e

    try:
        out_pdf = redact_pdf_by_rectangles(
            pdf_bytes,
            found_rects,
            apply_images=data.apply.apply_images,
            apply_graphics=data.apply.apply_graphics,
            sanitize_metadata=data.apply.sanitize_metadata,
            remove_annotations=data.apply.remove_annotations,
            remove_attachments=data.apply.remove_attachments,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Redaction failed") from e

    # 1) Audit interne cohérent avec la recherche
    try:
        internal_opts = build_audit_for_search(
            query=data.query,
            case_sensitive=data.options.case_sensitive,
            whole_word=data.options.whole_word,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        internal_report = audit_pdf_text(out_pdf, internal_opts)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"status": "error", "error": str(e)})

    if internal_report["status"] != "pass":
        return JSONResponse(status_code=400, content=internal_report)

    # 2) Audit additionnel (banlist) fourni par le client
    try:
        client_report = audit_pdf_text(
            out_pdf,
            AuditOptions(
                patterns=data.audit.patterns,
                regex=data.audit.regex,
                case_sensitive=data.audit.case_sensitive,
            ),
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"status": "error", "error": str(e)})

    if client_report["status"] != "pass":
        return JSONResponse(status_code=400, content=client_report)

    headers: dict[str, Any] = {
        "Content-Disposition": 'attachment; filename="redacted.pdf"',
        "X-Redaction-Audit-Status": "pass",
        "X-Redaction-Audit-Matches": "0",
        "X-Redaction-Search-Occurrences": str(len(found_rects)),
    }
    # On expose le report interne (cohérent) en header
    _add_report_headers(headers, internal_report)
    return Response(content=out_pdf, media_type="application/pdf", headers=headers)


def _build_presets_internal_audit_report(
    out_pdf: bytes,
    *,
    presets: list[str],
    pages: list[int] | None,
) -> dict[str, Any]:
    leaks_by_preset: dict[str, list[RedactionRect]] = {}
    total = 0
    matched_pages: set[int] = set()

    for p in presets:
        rects = find_redaction_rectangles_for_presets(out_pdf, [p], pages=pages)
        leaks_by_preset[p] = rects
        total += len(rects)
        matched_pages.update(r.page for r in rects)

    matches: list[dict[str, Any]] = []
    if total > 0:
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
                            "page": r.page,
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
        "options": {"mode": "presets_internal", "pages": pages},
        "presets": presets,
        "matches": matches,
    }


@app.post("/redact/presets")
async def redact_presets(
    file: Annotated[UploadFile, File(...)],
    payload: Annotated[str, Form(...)],
) -> Response:
    try:
        data = PresetsPayload.model_validate_json(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload JSON") from None

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty PDF upload")

    try:
        found_rects = find_redaction_rectangles_for_presets(
            pdf_bytes,
            data.presets,
            pages=data.scope.pages,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Presets search failed") from e

    try:
        out_pdf = redact_pdf_by_rectangles(
            pdf_bytes,
            found_rects,
            apply_images=data.options.apply_images,
            apply_graphics=data.options.apply_graphics,
            sanitize_metadata=data.options.sanitize_metadata,
            remove_annotations=data.options.remove_annotations,
            remove_attachments=data.options.remove_attachments,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Redaction failed") from e

    report = _build_presets_internal_audit_report(
        out_pdf,
        presets=data.presets,
        pages=data.scope.pages,
    )
    if report["total_matches"] != 0:
        return JSONResponse(status_code=400, content=report)

    headers: dict[str, Any] = {
        "Content-Disposition": 'attachment; filename="redacted.pdf"',
        "X-Redaction-Audit-Status": "pass",
        "X-Redaction-Audit-Matches": "0",
        "X-Redaction-Presets-Occurrences": str(len(found_rects)),
    }

    pass_report = {
        "status": "pass",
        "total_matches": 0,
        "matched_pages": [],
        "options": {"mode": "presets_internal", "pages": data.scope.pages},
        "presets": data.presets,
        "matches": [],
    }
    _add_report_headers(headers, pass_report)
    return Response(content=out_pdf, media_type="application/pdf", headers=headers)


@app.post("/redact/regex")
async def redact_regex(
    file: Annotated[UploadFile, File(...)],
    payload: Annotated[str, Form(...)],
) -> Response:
    try:
        data = RegexPayload.model_validate_json(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload JSON") from None

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty PDF upload")

    try:
        found_rects = find_redaction_rectangles_by_regex(
            pdf_bytes,
            data.patterns,
            case_sensitive=data.case_sensitive,
            pages=data.scope.pages,
            multiline=data.multiline,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Regex search failed") from e

    try:
        out_pdf = redact_pdf_by_rectangles(
            pdf_bytes,
            found_rects,
            apply_images=data.options.apply_images,
            apply_graphics=data.options.apply_graphics,
            sanitize_metadata=data.options.sanitize_metadata,
            remove_annotations=data.options.remove_annotations,
            remove_attachments=data.options.remove_attachments,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Redaction failed") from e

    try:
        report = audit_pdf_text(
            out_pdf,
            AuditOptions(
                patterns=data.audit.patterns,
                regex=data.audit.regex,
                case_sensitive=data.audit.case_sensitive,
            ),
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"status": "error", "error": str(e)})

    if report["status"] != "pass":
        return JSONResponse(status_code=400, content=report)

    headers: dict[str, Any] = {
        "Content-Disposition": 'attachment; filename="redacted.pdf"',
        "X-Redaction-Audit-Status": "pass",
        "X-Redaction-Audit-Matches": "0",
        "X-Redaction-Regex-Occurrences": str(len(found_rects)),
    }
    _add_report_headers(headers, report)
    return Response(content=out_pdf, media_type="application/pdf", headers=headers)


# ----------------------------
# Long-term endpoint: /redact/apply
# ----------------------------


class ApplySearchModel(BaseModel):
    query: str
    options: SearchOptionsModel = Field(default_factory=SearchOptionsModel)
    scope: ScopeModel = Field(default_factory=ScopeModel)

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("search.query must be non-empty")
        return v.strip()


class ApplyRegexModel(BaseModel):
    patterns: list[str]
    case_sensitive: bool = False
    multiline: bool = False
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


class ApplyPresetsModel(BaseModel):
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


class ApplyPayload(BaseModel):
    rects: list[RectModel] = Field(default_factory=list)

    # Compat existante (single)
    search: ApplySearchModel | None = None
    regex: ApplyRegexModel | None = None

    # NOUVEAU : multi-règles
    searches: list[ApplySearchModel] = Field(default_factory=list)
    regexes: list[ApplyRegexModel] = Field(default_factory=list)

    presets: ApplyPresetsModel | None = None
    options: OptionsModel = Field(default_factory=OptionsModel)
    audit: AuditModel | None = None


@app.post("/redact/apply")
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

    try:
        plan = plan_redactions(
            pdf_bytes,
            manual_rects=manual_rects,
            searches=searches_req or None,
            regexes=regexes_req or None,
            presets=presets_req,
        )

        out_pdf = apply_plan(
            pdf_bytes,
            plan,
            options=RedactionOptions(
                apply_images=data.options.apply_images,
                apply_graphics=data.options.apply_graphics,
                sanitize_metadata=data.options.sanitize_metadata,
                remove_annotations=data.options.remove_annotations,
                remove_attachments=data.options.remove_attachments,
            ),
        )
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
        "X-Redaction-Total-Occurrences": str(len(plan.all_rects)),
    }
    _add_report_headers(headers, composite)
    return Response(content=out_pdf, media_type="application/pdf", headers=headers)
