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
