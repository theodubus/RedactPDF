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
def test_redact_search_exact_email() -> None:
    pdf_path = FIXTURES_DIR / "002_email_phone_one_line.pdf"
    pdf_bytes = pdf_path.read_bytes()
    original_text = extract_text(pdf_bytes)

    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", original_text)
    assert m, "No email found in fixture 002_email_phone_one_line.pdf"
    email = m.group(0)

    payload = {
        "query": email,
        "options": {"case_sensitive": True, "whole_word": True},
        "scope": {"pages": None},
        "audit": {"patterns": [email], "regex": False, "case_sensitive": True},
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/search",
        files={"file": ("input.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"
    assert resp.headers.get("X-Redaction-Audit-Matches") == "0"

    redacted_text = extract_text(resp.content)
    assert email not in redacted_text


@pytest.mark.integration
def test_whole_word_does_not_match_substring_in_word() -> None:
    """
    Expected behavior:
    - query="CAT" with whole_word=True should NOT match "CATCH".
    - Fixture must contain both "CAT" and "CATCH", and only the standalone CAT
      should be redacted.
    - Audit uses regex with word boundaries to avoid failing due to "CAT" inside "CATCH".
    """
    pdf_path = FIXTURES_DIR / "007_whole_word_cat_catch.pdf"
    pdf_bytes = pdf_path.read_bytes()
    original_text = extract_text(pdf_bytes)

    assert "CAT" in original_text
    assert "CATCH" in original_text

    payload = {
        "query": "CAT",
        "options": {"case_sensitive": True, "whole_word": True},
        "scope": {"pages": None},
        "audit": {"patterns": [r"\bCAT\b"], "regex": True, "case_sensitive": True},
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/search",
        files={"file": ("input.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"
    assert resp.headers.get("X-Redaction-Audit-Matches") == "0"

    redacted_text = extract_text(resp.content)

    assert re.search(r"\bCAT\b", redacted_text) is None
    assert "CATCH" in redacted_text


@pytest.mark.integration
def test_whole_word_handles_punctuation_and_email_subtoken() -> None:
    """
    Regression coverage for whole_word=True with boundary-aware regex:

    - Must match 'DUPONT,' (punctuation boundary)
    - Must also match 'dupont' inside an email local-part ('.' and '@' are boundaries)
    - After redaction, no whole-word 'dupont' should remain (case-insensitive)
    """
    pdf_path = FIXTURES_DIR / "011_apply_search_and_email.pdf"
    pdf_bytes = pdf_path.read_bytes()
    original_text = extract_text(pdf_bytes)

    assert "DUPONT" in original_text
    assert "alice.dupont@example.com" in original_text

    payload = {
        "query": "DUPONT",
        "options": {"case_sensitive": False, "whole_word": True},
        "scope": {"pages": None},
        # Audit cohérent avec whole_word=True : regex frontières basées sur \w
        "audit": {
            "patterns": [r"(?<!\w)DUPONT(?!\w)"],
            "regex": True,
            "case_sensitive": False,
        },
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/search",
        files={"file": ("input.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"
    assert resp.headers.get("X-Redaction-Audit-Matches") == "0"

    redacted_text = extract_text(resp.content)

    # Aucun token whole-word restant
    assert re.search(r"(?i)\bdupont\b", redacted_text) is None

    # Non-régression : du texte non sensible doit rester
    assert "Texte non sensible" in redacted_text
