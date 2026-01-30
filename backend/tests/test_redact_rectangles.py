from __future__ import annotations

import json
import re
from io import BytesIO
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.main import app

CLIENT = TestClient(app)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "generated"
SECRET_FIXTURE = FIXTURES_DIR / "001_secret_text.pdf"
SECRET = "SECRET_ABC123"


def extract_text_with_pypdf(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def pick_non_secret_token(text: str) -> str:
    # Cherche un mot "simple" qui n'est pas le secret, pour vérifier qu'on n'a pas cassé le reste.
    words = re.findall(r"[A-Za-z]{4,}", text)
    for w in words:
        if "SECRET" not in w:
            return w
    # Fallback : au pire, on vérifie qu'il reste quelque chose.
    return "Fixture"


def find_secret_rect_with_pymupdf(pdf_bytes: bytes) -> dict:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[0]
        rects = page.search_for(SECRET)
        assert rects, "SECRET not found by PyMuPDF search_for"
        r = rects[0].normalize()
        return {"page": 0, "x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1}
    finally:
        doc.close()


@pytest.mark.integration
def test_redact_rectangles_removes_secret_and_preserves_other_text() -> None:
    pdf_in = SECRET_FIXTURE.read_bytes()
    original_text = extract_text_with_pypdf(pdf_in)
    assert SECRET in original_text

    keep_token = pick_non_secret_token(original_text)

    rect = find_secret_rect_with_pymupdf(pdf_in)
    payload = {
        "rects": [rect],
        "options": {"apply_images": False, "apply_graphics": False},
    }

    resp = CLIENT.post(
        "/redact/rectangles",
        files={"file": ("input.pdf", pdf_in, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")

    pdf_out = resp.content
    out_text = extract_text_with_pypdf(pdf_out)

    assert SECRET not in out_text, "Secret should be removed from extracted text"
    assert keep_token in out_text, "Non-targeted text should remain extractible"


@pytest.mark.integration
def test_redact_rectangles_wrong_rect_does_not_remove_secret() -> None:
    pdf_in = SECRET_FIXTURE.read_bytes()

    # Rectangle volontairement à côté (décalage horizontal)
    rect = find_secret_rect_with_pymupdf(pdf_in)
    rect["x0"] += 200
    rect["x1"] += 200

    payload = {"rects": [rect], "options": {"apply_images": False, "apply_graphics": False}}

    resp = CLIENT.post(
        "/redact/rectangles",
        files={"file": ("input.pdf", pdf_in, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )
    assert resp.status_code == 200

    out_text = extract_text_with_pypdf(resp.content)
    assert SECRET in out_text, "Secret should still be present if we redact the wrong area"
