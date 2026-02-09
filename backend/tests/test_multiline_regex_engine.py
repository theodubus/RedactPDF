# tests/test_multiline_regex_engine.py
from __future__ import annotations

from pathlib import Path

import pytest

from app.multiline_regex_engine import find_redaction_rectangles_by_regex

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "generated"


@pytest.mark.integration
def test_regex_ignore_accents_matches_leo_and_leo_accented() -> None:
    pdf_bytes = (FIXTURES_DIR / "012_ignore_accents.pdf").read_bytes()

    # "Leo" should match "Léo" when ignore_accents=True
    rects_1 = find_redaction_rectangles_by_regex(
        pdf_bytes,
        ["Leo"],
        case_sensitive=False,
        multiline=False,
        ignore_accents=True,
    )
    assert rects_1, 'Expected matches for pattern "Leo" with ignore_accents=True'

    # "Léo" should match "Leo" when ignore_accents=True
    rects_2 = find_redaction_rectangles_by_regex(
        pdf_bytes,
        ["Léo"],
        case_sensitive=False,
        multiline=False,
        ignore_accents=True,
    )
    assert rects_2, 'Expected matches for pattern "Léo" with ignore_accents=True'
