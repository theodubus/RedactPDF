from __future__ import annotations

import base64
import json
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError, field_validator
from starlette.responses import Response

from app.audit import AuditOptions, audit_pdf_text
from app.redaction import RedactionRect, redact_pdf_by_rectangles

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class RectModel(BaseModel):
    page: int = Field(ge=0)
    x0: float
    y0: float
    x1: float
    y1: float


class OptionsModel(BaseModel):
    apply_images: bool = False
    apply_graphics: bool = False


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
    options: OptionsModel = OptionsModel()
    audit: AuditModel


@app.post("/redact/rectangles")
async def redact_rectangles(
    file: Annotated[UploadFile, File(...)],
    payload: Annotated[str, Form(...)],
) -> Response:
    # 1) Parser payload JSON
    try:
        data = RectanglesPayload.model_validate_json(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e
    except Exception:
        # payload pas JSON ou autre erreur de parsing
        raise HTTPException(status_code=400, detail="Invalid payload JSON") from None

    # 2) Lire PDF
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty PDF upload")

    # 3) Appliquer redactions
    # NOTE: options images/vectors sont ignorées dans cette étape (forcées OFF côté service)
    rects = [
        RedactionRect(
            page=r.page,
            x0=r.x0,
            y0=r.y0,
            x1=r.x1,
            y1=r.y1,
        )
        for r in data.rects
    ]

    try:
        out_pdf = redact_pdf_by_rectangles(pdf_bytes, rects)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Redaction failed") from e

    # 4) Audit post-export (pilier de sécurité)
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
        # regex invalide, patterns vides, etc.
        return JSONResponse(
            status_code=400,
            content={"status": "error", "error": str(e)},
        )

    if report["status"] != "pass":
        return JSONResponse(status_code=400, content=report)

    # 5) Succès : renvoyer PDF + headers d'audit
    headers: dict[str, Any] = {
        "Content-Disposition": 'attachment; filename="redacted.pdf"',
        "X-Redaction-Audit-Status": "pass",
        "X-Redaction-Audit-Matches": "0",
    }

    # Optionnel : inclure un report encodé (attention aux limites de taille de header)
    report_json = json.dumps(report, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    b64 = base64.urlsafe_b64encode(report_json).decode("ascii")

    # Limite conservative pour éviter des soucis proxies/serveurs
    if len(b64) <= 6000:
        headers["X-Redaction-Audit-Report-B64"] = b64
    else:
        headers["X-Redaction-Audit-Report-Truncated"] = "1"

    return Response(content=out_pdf, media_type="application/pdf", headers=headers)
