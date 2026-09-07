from __future__ import annotations

import json
import re
from pathlib import Path

import phonenumbers
import pytest
from fastapi.testclient import TestClient

from redactpdf.main import app
from tests.utils_pdf import extract_text

client = TestClient(app)

EMAIL_RX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

CC_DIGITS_VALID = "4111111111111111"
CC_DIGITS_INVALID = "4111111111111112"


def _digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s)


# Résolu depuis ce fichier, pas depuis le répertoire courant : la suite doit
# passer quel que soit l'endroit d'où pytest est lancé.
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "generated"


def _load_fixture(name: str) -> bytes:
    path = FIXTURES_DIR / name
    return path.read_bytes()


def _post_apply_presets(pdf_bytes: bytes, *, presets: list[str], audit: dict | None):
    payload = {
        "rects": [],
        "presets": {"presets": presets, "scope": {"pages": None}},
        "options": {"apply_graphics": False},
        "audit": audit,
    }
    files = {"file": ("input.pdf", pdf_bytes, "application/pdf")}
    data = {"payload": json.dumps(payload)}
    return client.post("/redact/apply", files=files, data=data)


def _extract_first_phone(text: str, region: str = "FR") -> str | None:
    matches = list(phonenumbers.PhoneNumberMatcher(text, region))
    if not matches:
        return None
    return matches[0].raw_string


@pytest.mark.integration
def test_presets_email_removes_email_keeps_phone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDACT_DEFAULT_REGION", "FR")

    pdf_in = _load_fixture("002_email_phone_one_line.pdf")
    text_in = extract_text(pdf_in)

    email_m = EMAIL_RX.search(text_in)
    assert email_m is not None, "Expected an email in fixture 002."
    email = email_m.group(0)

    phone = _extract_first_phone(text_in, region="FR")
    assert phone is not None, "Expected a phone number in fixture 002."

    resp = _post_apply_presets(
        pdf_in,
        presets=["email"],
        audit={"patterns": [email], "regex": False, "case_sensitive": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"
    assert int(resp.headers.get("X-Redaction-Audit-Matches", "999")) == 0
    assert int(resp.headers.get("X-Redaction-Presets-Occurrences", "0")) > 0

    text_out = extract_text(resp.content)
    assert email not in text_out
    assert phone in text_out


@pytest.mark.integration
def test_presets_phone_removes_phone_keeps_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDACT_DEFAULT_REGION", "FR")

    pdf_in = _load_fixture("002_email_phone_one_line.pdf")
    text_in = extract_text(pdf_in)

    email_m = EMAIL_RX.search(text_in)
    assert email_m is not None, "Expected an email in fixture 002."
    email = email_m.group(0)

    phone = _extract_first_phone(text_in, region="FR")
    assert phone is not None, "Expected a phone number in fixture 002."

    resp = _post_apply_presets(
        pdf_in,
        presets=["phone"],
        audit={"patterns": [phone], "regex": False, "case_sensitive": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"
    assert int(resp.headers.get("X-Redaction-Audit-Matches", "999")) == 0
    assert int(resp.headers.get("X-Redaction-Presets-Occurrences", "0")) > 0

    text_out = extract_text(resp.content)
    assert phone not in text_out
    assert email in text_out


@pytest.mark.integration
def test_presets_credit_card_luhn_filters_invalid() -> None:
    pdf_in = _load_fixture("008_credit_card_luhn.pdf")
    text_in = extract_text(pdf_in)

    digits_in = _digits_only(text_in)
    assert CC_DIGITS_VALID in digits_in
    assert CC_DIGITS_INVALID in digits_in

    resp = _post_apply_presets(
        pdf_in,
        presets=["credit_card"],
        audit={
            "patterns": [r"\b4111[ -]*1111[ -]*1111[ -]*1111\b"],
            "regex": True,
            "case_sensitive": True,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"
    assert int(resp.headers.get("X-Redaction-Audit-Matches", "999")) == 0
    assert int(resp.headers.get("X-Redaction-Presets-Occurrences", "0")) > 0

    text_out = extract_text(resp.content)
    digits_out = _digits_only(text_out)
    assert CC_DIGITS_VALID not in digits_out, "Valid PAN must be redacted."
    assert CC_DIGITS_INVALID in digits_out, "Invalid PAN must remain (Luhn filter)."


@pytest.mark.integration
def test_presets_email_no_false_positive_on_secret_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDACT_DEFAULT_REGION", "FR")

    pdf_in = _load_fixture("001_secret_text.pdf")
    text_in = extract_text(pdf_in)
    assert "SECRET_ABC123" in text_in

    resp = _post_apply_presets(
        pdf_in,
        presets=["email"],
        audit={"patterns": ["SHOULD_NOT_EXIST_123"], "regex": False, "case_sensitive": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"
    assert int(resp.headers.get("X-Redaction-Presets-Occurrences", "999")) == 0

    text_out = extract_text(resp.content)
    assert "SECRET_ABC123" in text_out, "Preset email must not remove unrelated text."
