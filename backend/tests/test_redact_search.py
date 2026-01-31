# backend/tests/test_redact_search.py
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.main import app

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "generated"


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(_BytesIO(pdf_bytes))
    text_parts: list[str] = []
    for page in reader.pages:
        text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


class _BytesIO:
    # tiny wrapper to avoid importing io.BytesIO in every file
    def __init__(self, b: bytes) -> None:
        self._b = b
        self._i = 0

    def read(self, n: int = -1) -> bytes:
        if n == -1:
            n = len(self._b) - self._i
        chunk = self._b[self._i : self._i + n]
        self._i += len(chunk)
        return chunk

    def seek(self, pos: int, whence: int = 0) -> int:
        if whence == 0:
            self._i = pos
        elif whence == 1:
            self._i += pos
        elif whence == 2:
            self._i = len(self._b) + pos
        else:
            raise ValueError("invalid whence")
        return self._i

    def tell(self) -> int:
        return self._i


@pytest.mark.integration
def test_redact_search_exact_email() -> None:
    pdf_path = FIXTURES_DIR / "002_email_phone_one_line.pdf"
    pdf_bytes = pdf_path.read_bytes()
    original_text = _extract_text(pdf_bytes)

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

    redacted_text = _extract_text(resp.content)
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
    original_text = _extract_text(pdf_bytes)

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

    redacted_text = _extract_text(resp.content)

    # Ensure standalone CAT is gone (whole word)
    assert re.search(r"\bCAT\b", redacted_text) is None
    # Ensure CATCH is still present
    assert "CATCH" in redacted_text
