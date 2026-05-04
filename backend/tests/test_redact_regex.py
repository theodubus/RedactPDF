from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.utils_pdf import extract_text

client = TestClient(app)

EMAIL_RX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RX = re.compile(r"(?:\+?\d[\d\s().-]{6,}\d)")


def _load_fixture(name: str) -> bytes:
    path = Path("tests/fixtures/generated") / name
    return path.read_bytes()


def _post_apply_regex(pdf_bytes: bytes, *, patterns: list[str], case_sensitive: bool, audit: dict):
    payload = {
        "rects": [],
        "regexes": [
            {
                "patterns": patterns,
                "case_sensitive": case_sensitive,
                "multiline": False,
                "scope": {"pages": None},
            }
        ],
        "options": {"apply_images": False, "apply_graphics": False},
        "audit": audit,
    }
    files = {"file": ("input.pdf", pdf_bytes, "application/pdf")}
    data = {"payload": json.dumps(payload)}
    return client.post("/redact/apply", files=files, data=data)


@pytest.mark.integration
def test_regex_email_removes_email_keeps_phone() -> None:
    pdf_in = _load_fixture("002_email_phone_one_line.pdf")
    text_in = extract_text(pdf_in)

    email_m = EMAIL_RX.search(text_in)
    assert email_m is not None, "Expected an email in fixture 002."
    email = email_m.group(0)

    phone_m = PHONE_RX.search(text_in)
    assert phone_m is not None, "Expected a phone-like string in fixture 002."
    phone = phone_m.group(0)

    email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"

    resp = _post_apply_regex(
        pdf_in,
        patterns=[email_pattern],
        case_sensitive=False,
        audit={"patterns": [email_pattern], "regex": True, "case_sensitive": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"
    assert int(resp.headers.get("X-Redaction-Audit-Matches", "999")) == 0
    assert int(resp.headers.get("X-Redaction-Regex-Occurrences", "0")) > 0

    text_out = extract_text(resp.content)
    assert email not in text_out
    assert phone in text_out


@pytest.mark.integration
def test_regex_phone_removes_phone_keeps_email() -> None:
    pdf_in = _load_fixture("002_email_phone_one_line.pdf")
    text_in = extract_text(pdf_in)

    email_m = EMAIL_RX.search(text_in)
    assert email_m is not None, "Expected an email in fixture 002."
    email = email_m.group(0)

    phone_m = PHONE_RX.search(text_in)
    assert phone_m is not None, "Expected a phone-like string in fixture 002."
    phone = phone_m.group(0)

    phone_pattern = r"(?:\+?\d[\d\s().-]{6,}\d)"

    resp = _post_apply_regex(
        pdf_in,
        patterns=[phone_pattern],
        case_sensitive=False,
        audit={"patterns": [phone_pattern], "regex": True, "case_sensitive": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"
    assert int(resp.headers.get("X-Redaction-Audit-Matches", "999")) == 0
    assert int(resp.headers.get("X-Redaction-Regex-Occurrences", "0")) > 0

    text_out = extract_text(resp.content)
    assert phone not in text_out
    assert email in text_out


@pytest.mark.integration
def test_regex_invalid_pattern_returns_400() -> None:
    pdf_in = _load_fixture("002_email_phone_one_line.pdf")

    resp = _post_apply_regex(
        pdf_in,
        patterns=["["],  # invalid regex
        case_sensitive=False,
        audit={"patterns": ["SHOULD_NOT_EXIST_123"], "regex": False, "case_sensitive": True},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "detail" in body or "error" in body or "status" in body


@pytest.mark.integration
def test_regex_no_match_occurrences_zero_and_content_preserved() -> None:
    pdf_in = _load_fixture("002_email_phone_one_line.pdf")
    text_in = extract_text(pdf_in)

    no_match_pattern = r"THIS_WILL_NOT_MATCH_123456"

    resp = _post_apply_regex(
        pdf_in,
        patterns=[no_match_pattern],
        case_sensitive=False,
        audit={"patterns": [no_match_pattern], "regex": True, "case_sensitive": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"
    assert int(resp.headers.get("X-Redaction-Audit-Matches", "999")) == 0

    if "X-Redaction-Regex-Occurrences" in resp.headers:
        assert int(resp.headers["X-Redaction-Regex-Occurrences"]) == 0

    text_out = extract_text(resp.content)
    assert text_out == text_in
