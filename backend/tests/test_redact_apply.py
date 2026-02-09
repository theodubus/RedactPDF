from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.utils_pdf import extract_text

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "generated"


@pytest.mark.integration
def test_redact_apply_combines_search_and_presets_email() -> None:
    """
    Long-term regression test:
    - /redact/apply computes rectangles from the ORIGINAL PDF for search + presets,
      so email redaction cannot be broken by a prior partial search redaction.
    """
    pdf_path = FIXTURES_DIR / "011_apply_search_and_email.pdf"
    pdf_bytes = pdf_path.read_bytes()

    original_text = extract_text(pdf_bytes)
    assert "DUPONT" in original_text
    assert "alice.dupont@example.com" in original_text

    payload = {
        "rects": [],
        "search": {
            "query": "DUPONT",
            "options": {"case_sensitive": False, "whole_word": True},
            "scope": {"pages": None},
        },
        "presets": {
            "presets": ["email"],
            "scope": {"pages": None},
        },
        "options": {},
        # audit additionnel (optionnel) : on bannit le nom en sortie
        "audit": {"patterns": ["DUPONT"], "regex": False, "case_sensitive": False},
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"
    assert resp.headers.get("X-Redaction-Audit-Matches") == "0"

    redacted_text = extract_text(resp.content)

    # Email must be fully removed (no partial leftovers)
    assert "alice.dupont@example.com" not in redacted_text
    assert "dupont" not in redacted_text.casefold()

    # Ensure other content remains
    assert "Texte non sensible" in redacted_text

    # Optional: ensure no remaining whole-word name token
    assert re.search(r"(?i)\bdupont\b", redacted_text) is None


@pytest.mark.integration
def test_redact_apply_multiple_searches_and_presets() -> None:
    pdf_path = FIXTURES_DIR / "011_apply_search_and_email.pdf"
    pdf_bytes = pdf_path.read_bytes()

    original_text = extract_text(pdf_bytes)
    assert "DUPONT" in original_text
    assert "alice.dupont@example.com" in original_text
    assert "Texte non sensible" in original_text

    payload = {
        "rects": [],
        "searches": [
            {
                "query": "DUPONT",
                "options": {"case_sensitive": False, "whole_word": True},
                "scope": {"pages": None},
            },
            {
                "query": "Texte non sensible",
                "options": {"case_sensitive": False, "whole_word": False},
                "scope": {"pages": None},
            },
        ],
        "presets": {"presets": ["email"], "scope": {"pages": None}},
        "options": {},
        "audit": None,
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"
    assert resp.headers.get("X-Redaction-Audit-Matches") == "0"

    # Occurrences headers should exist
    assert resp.headers.get("X-Redaction-Search-Occurrences") is not None
    assert resp.headers.get("X-Redaction-Presets-Occurrences") is not None

    redacted_text = extract_text(resp.content)

    assert re.search(r"(?i)\bdupont\b", redacted_text) is None
    assert "Texte non sensible" not in redacted_text
    assert "alice.dupont@example.com" not in redacted_text

    # Not fully blank
    assert redacted_text.strip() != ""


@pytest.mark.integration
def test_redact_apply_multiple_regexes_email_and_phone() -> None:
    pdf_path = FIXTURES_DIR / "002_email_phone_one_line.pdf"
    pdf_bytes = pdf_path.read_bytes()

    original_text = extract_text(pdf_bytes)
    assert original_text.strip() != ""

    email_pat = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    phone_pat = r"(?:\+?\d[\d .()\-\s]{6,}\d)"

    assert re.search(email_pat, original_text) is not None
    assert re.search(phone_pat, original_text) is not None

    payload = {
        "rects": [],
        "regexes": [
            {
                "patterns": [email_pat],
                "case_sensitive": False,
                "multiline": False,
                "scope": {"pages": None},
            },
            {
                "patterns": [phone_pat],
                "case_sensitive": False,
                "multiline": False,
                "scope": {"pages": None},
            },
        ],
        "options": {},
        "audit": None,
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"

    redacted_text = extract_text(resp.content)

    assert re.search(email_pat, redacted_text, flags=re.IGNORECASE) is None
    assert re.search(phone_pat, redacted_text, flags=re.IGNORECASE) is None


@pytest.mark.integration
def test_redact_apply_multiline_regex_rule() -> None:
    pdf_path = FIXTURES_DIR / "003_phone_two_lines.pdf"
    pdf_bytes = pdf_path.read_bytes()

    original_text = extract_text(pdf_bytes)
    assert original_text.strip() != ""

    # Pattern qui tolère les retours ligne (via \s)
    phone_pat = r"(?:\+?\d[\d\s().\-]{6,}\d)"
    assert re.search(phone_pat, original_text) is not None

    payload = {
        "rects": [],
        "regexes": [
            {
                "patterns": [phone_pat],
                "case_sensitive": False,
                "multiline": True,
                "scope": {"pages": None},
            }
        ],
        "options": {},
        "audit": None,
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"

    redacted_text = extract_text(resp.content)
    assert re.search(phone_pat, redacted_text, flags=re.IGNORECASE) is None


@pytest.mark.integration
def test_redact_apply_invalid_regex_in_regexes_returns_400() -> None:
    pdf_path = FIXTURES_DIR / "001_secret_text.pdf"
    pdf_bytes = pdf_path.read_bytes()

    payload = {
        "rects": [],
        "regexes": [
            {
                "patterns": ["([A-"],
                "case_sensitive": False,
                "multiline": False,
                "scope": {"pages": None},
            }
        ],
        "options": {},
        "audit": None,
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 400
