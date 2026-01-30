from __future__ import annotations

from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, ValidationError
from starlette.responses import Response

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


class RectanglesPayload(BaseModel):
    rects: list[RectModel]
    options: OptionsModel = OptionsModel()


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


    headers: dict[str, Any] = {
        "Content-Disposition": 'attachment; filename="redacted.pdf"'
    }
    return Response(content=out_pdf, media_type="application/pdf", headers=headers)
