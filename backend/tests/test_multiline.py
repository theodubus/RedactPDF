from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.utils_pdf import extract_text

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "generated"


def _load_pdf(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


PHONE_REGEX = r"06\s+12\s+34\s+56\s+78"


@pytest.mark.integration
def test_presets_phone_multiline_two_lines_is_redacted() -> None:
    client = TestClient(app)
    pdf_in = _load_pdf("003_phone_two_lines.pdf")

    payload = {
        "presets": ["phone"],
        "audit": {
            "patterns": [PHONE_REGEX],
            "regex": True,
            "case_sensitive": False,
        },
        # options exist in your schema; keep minimal if your API ignores options for now
        "options": {},
    }

    resp = client.post(
        "/redact/presets",
        files={
            "file": ("in.pdf", pdf_in, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )

    assert resp.status_code == 200, resp.text
    pdf_out = resp.content
    text_out = extract_text(pdf_out)
    assert re.search(PHONE_REGEX, text_out, flags=re.IGNORECASE) is None


@pytest.mark.integration
def test_regex_endpoint_multiline_can_match_across_two_lines() -> None:
    client = TestClient(app)
    pdf_in = _load_pdf("003_phone_two_lines.pdf")

    payload = {
        "patterns": [PHONE_REGEX],
        "case_sensitive": False,
        "multiline": True,
        "audit": {
            "patterns": [PHONE_REGEX],
            "regex": True,
            "case_sensitive": False,
        },
        "options": {},
        "scope": {"pages": None},
    }

    resp = client.post(
        "/redact/regex",
        files={
            "file": ("in.pdf", pdf_in, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )

    assert resp.status_code == 200, resp.text
    pdf_out = resp.content
    text_out = extract_text(pdf_out)
    assert re.search(PHONE_REGEX, text_out, flags=re.IGNORECASE) is None


@pytest.mark.integration
def test_multiline_does_not_cross_columns_trap_fixture() -> None:
    """
    This test requires adding a dedicated fixture, see instructions:
      009_cross_column_phone_trap.pdf

    The goal: if a naive engine concatenates adjacent lines globally, it might match the phone.
    Our engine should avoid pairing across columns and return 0 occurrences.
    """
    client = TestClient(app)
    pdf_in = _load_pdf("009_cross_column_phone_trap.pdf")

    payload = {
        "patterns": [PHONE_REGEX],
        "case_sensitive": False,
        "multiline": True,
        "audit": {
            # audit should not fail; we are not trying to redact this doc,
            # just ensure no accidental match
            "patterns": ["___definitely_not_present___"],
            "regex": False,
            "case_sensitive": False,
        },
        "options": {},
        "scope": {"pages": None},
    }

    resp = client.post(
        "/redact/regex",
        files={
            "file": ("in.pdf", pdf_in, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )

    assert resp.status_code == 200, resp.text
    # Check occurrences header if your endpoint sets it:
    # If header name differs, adapt in second pass with your current code.
    occ = resp.headers.get("X-Redaction-Regex-Occurrences")
    assert occ is not None
    assert int(occ) == 0
