# backend/app/search.py
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pymupdf

from app.audit import build_whole_word_pattern
from app.multiline_regex_engine import find_redaction_rectangles_by_regex
from app.redaction import RedactionRect


@dataclass(frozen=True)
class SearchOptions:
    query: str
    case_sensitive: bool = False
    whole_word: bool = False
    pages: Sequence[int] | None = None
    sort_words: bool = True


def find_redaction_rectangles(pdf_bytes: bytes, opts: SearchOptions) -> list[RedactionRect]:
    """
    Return a list of RedactionRect (page + coordinates in PyMuPDF space)
    for occurrences of opts.query.

    Strategy:
    - whole_word=True: build a boundary-aware regex and reuse the regex engine
      (more robust than relying on page.get_text("words") tokenization, which may
      include punctuation like "DUPONT," or embed substrings inside emails).
    - whole_word=False: use page.search_for(query) (fast, can wrap across lines,
      but case-insensitive for ASCII), then filter by exact-case using get_textbox()
      if case_sensitive=True.

    Notes:
    - Page.search_for() is case-insensitive for ASCII and does not support regex.
      See PyMuPDF docs.
    - The boundary rule for whole_word uses \\w (letters/digits/_). Punctuation
      such as ',', '.', '@' acts as a boundary, which is desirable for names next
      to punctuation and substrings inside emails.
    """
    query = (opts.query or "").strip()
    if not query:
        raise ValueError("query must be non-empty")

    if opts.whole_word:
        pattern = build_whole_word_pattern(query)
        # Reuse the existing regex->rectangles engine (single-line mode).
        # This avoids fragile dependence on PyMuPDF "words" tokenization.
        return find_redaction_rectangles_by_regex(
            pdf_bytes=pdf_bytes,
            patterns=[pattern],
            case_sensitive=opts.case_sensitive,
            pages=opts.pages,
            multiline=False,
        )

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_numbers = _resolve_pages(doc.page_count, opts.pages)
        rects: list[RedactionRect] = []

        for pno in page_numbers:
            page = doc.load_page(pno)
            rects.extend(_find_substring_like(page, pno, query, opts.case_sensitive))

        return rects
    finally:
        doc.close()


def _resolve_pages(page_count: int, pages: Sequence[int] | None) -> list[int]:
    if pages is None:
        return list(range(page_count))
    if len(pages) == 0:
        return list(range(page_count))

    out: list[int] = []
    for p in pages:
        if p < 0 or p >= page_count:
            raise ValueError(f"Invalid page index {p}. Must be in [0, {page_count - 1}].")
        out.append(int(p))
    # keep order but remove duplicates
    seen: set[int] = set()
    unique: list[int] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _find_substring_like(
    page: pymupdf.Page,
    pno: int,
    query: str,
    case_sensitive: bool,
) -> list[RedactionRect]:
    # search_for is case-insensitive for ASCII; it can wrap across lines. (docs)
    candidates = page.search_for(query)

    if not case_sensitive:
        return [_rect_to_model(pno, r) for r in candidates]

    # Case-sensitive filtering: keep only those rectangles whose boxed text
    # contains the query with exact casing (after whitespace normalization).
    needle = _collapse_ws(query)
    out: list[RedactionRect] = []
    for r in candidates:
        boxed = page.get_textbox(r)  # may include newlines / extra spaces
        hay = _collapse_ws(boxed)
        if needle in hay:
            out.append(_rect_to_model(pno, r))
    return out


def _rect_to_model(pno: int, r: pymupdf.Rect) -> RedactionRect:
    return RedactionRect(page=pno, x0=float(r.x0), y0=float(r.y0), x1=float(r.x1), y1=float(r.y1))


def _collapse_ws(s: str) -> str:
    # Collapse all whitespace (spaces/newlines/tabs) into single spaces
    return " ".join((s or "").split())
