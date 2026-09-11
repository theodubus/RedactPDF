from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from redactpdf.main import app
from tests.utils_pdf import extract_text

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "generated"


def _load_pdf(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


PHONE_REGEX = r"06\s+12\s+34\s+56\s+78"


def _post_apply(pdf_bytes: bytes, payload: dict):
    client = TestClient(app)
    return client.post(
        "/redact/apply",
        files={
            "file": ("in.pdf", pdf_bytes, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )


@pytest.mark.integration
def test_presets_phone_multiline_two_lines_is_redacted() -> None:
    pdf_in = _load_pdf("003_phone_two_lines.pdf")

    payload = {
        "rects": [],
        "presets": {"presets": ["phone"], "scope": {"pages": None}},
        "audit": {
            "patterns": [PHONE_REGEX],
            "regex": True,
            "case_sensitive": False,
        },
        "options": {},
    }

    resp = _post_apply(pdf_in, payload)
    assert resp.status_code == 200, resp.text
    text_out = extract_text(resp.content)
    assert re.search(PHONE_REGEX, text_out, flags=re.IGNORECASE) is None


@pytest.mark.integration
def test_regex_endpoint_multiline_can_match_across_two_lines() -> None:
    pdf_in = _load_pdf("003_phone_two_lines.pdf")

    payload = {
        "rects": [],
        "regexes": [
            {
                "patterns": [PHONE_REGEX],
                "case_sensitive": False,
                "multiline": True,
                "scope": {"pages": None},
            }
        ],
        "audit": {
            "patterns": [PHONE_REGEX],
            "regex": True,
            "case_sensitive": False,
        },
        "options": {},
    }

    resp = _post_apply(pdf_in, payload)
    assert resp.status_code == 200, resp.text
    text_out = extract_text(resp.content)
    assert re.search(PHONE_REGEX, text_out, flags=re.IGNORECASE) is None


@pytest.mark.integration
def test_multiline_does_not_cross_columns_trap_fixture() -> None:
    """
    The geometric engine must not pair lines across columns.
    Tested directly on the engine: the API audit re-runs regex on flattened
    page text where '\\s+' matches the column boundary newline, which would
    spuriously hit even though the engine correctly returned 0 rects.
    """
    from redactpdf.multiline_regex_engine import find_redaction_rectangles_by_regex

    pdf_in = _load_pdf("009_cross_column_phone_trap.pdf")
    rects = find_redaction_rectangles_by_regex(
        pdf_in,
        [PHONE_REGEX],
        case_sensitive=False,
        multiline=True,
    )
    assert len(rects) == 0
