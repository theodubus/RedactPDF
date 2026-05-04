from __future__ import annotations

import json
import re
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.utils_pdf import extract_text

CLIENT = TestClient(app)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "generated"
SECRET_FIXTURE = FIXTURES_DIR / "001_secret_text.pdf"
SECRET = "SECRET_ABC123"


def pick_non_secret_token(text: str) -> str:
    words = re.findall(r"[A-Za-z]{4,}", text)
    for w in words:
        if "SECRET" not in w:
            return w
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


def make_payload(rects: list[dict], patterns: list[str]) -> dict:
    return {
        "rects": rects,
        "options": {"apply_images": False, "apply_graphics": False},
        "audit": {"patterns": patterns, "regex": False, "case_sensitive": True},
    }


def _post_apply(pdf_bytes: bytes, payload: dict):
    return CLIENT.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )


@pytest.mark.integration
def test_redact_rectangles_removes_secret_and_preserves_other_text() -> None:
    pdf_in = SECRET_FIXTURE.read_bytes()
    original_text = extract_text(pdf_in)
    assert SECRET in original_text

    keep_token = pick_non_secret_token(original_text)

    rect = find_secret_rect_with_pymupdf(pdf_in)
    payload = make_payload([rect], patterns=[SECRET])

    resp = _post_apply(pdf_in, payload)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")

    assert resp.headers.get("x-redaction-audit-status") == "pass"
    assert resp.headers.get("x-redaction-audit-matches") == "0"

    pdf_out = resp.content
    out_text = extract_text(pdf_out)

    assert SECRET not in out_text, "Secret should be removed from extracted text"
    assert keep_token in out_text, "Non-targeted text should remain extractible"


@pytest.mark.integration
def test_redact_rectangles_wrong_rect_triggers_audit_fail() -> None:
    pdf_in = SECRET_FIXTURE.read_bytes()

    rect = find_secret_rect_with_pymupdf(pdf_in)
    rect["x0"] += 200
    rect["x1"] += 200

    payload = make_payload([rect], patterns=[SECRET])

    resp = _post_apply(pdf_in, payload)

    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/json")

    report = resp.json()
    assert report["status"] == "fail"
    audit_report = report["components"]["audit"]
    assert audit_report["total_matches"] >= 1
    assert SECRET in audit_report["patterns"]

    assert any(
        (SECRET in m.get("match", "")) or (SECRET in m.get("snippet", ""))
        for m in audit_report.get("matches", [])
    ), "Audit report should include evidence that the secret remains"


@pytest.mark.integration
def test_redaction_does_not_modify_original_fixture_on_disk() -> None:
    before_bytes = SECRET_FIXTURE.read_bytes()
    assert SECRET in extract_text(before_bytes)

    rect = find_secret_rect_with_pymupdf(before_bytes)
    payload = make_payload([rect], patterns=[SECRET])

    resp = _post_apply(before_bytes, payload)
    assert resp.status_code == 200

    after_bytes = SECRET_FIXTURE.read_bytes()
    assert before_bytes == after_bytes, "Fixture PDF on disk must remain byte-identical"
    assert SECRET in extract_text(after_bytes), "Original must still contain the secret"


@pytest.mark.integration
def test_redact_rectangles_full_page_rect_redacts_target() -> None:
    pdf_in = SECRET_FIXTURE.read_bytes()
    original_text = extract_text(pdf_in)
    assert SECRET in original_text

    doc = pymupdf.open(stream=pdf_in, filetype="pdf")
    try:
        page = doc[0]
        bounds = page.rect
        full_page_rect = {
            "page": 0,
            "x0": bounds.x0,
            "y0": bounds.y0,
            "x1": bounds.x1,
            "y1": bounds.y1,
        }
    finally:
        doc.close()

    payload = make_payload([full_page_rect], patterns=[SECRET])

    resp = _post_apply(pdf_in, payload)

    assert resp.status_code == 200
    assert resp.headers.get("x-redaction-audit-status") == "pass"

    out_text = extract_text(resp.content)
    assert SECRET not in out_text
