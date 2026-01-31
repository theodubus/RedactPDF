# backend/app/search.py
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pymupdf

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
    - whole_word=True: use page.get_text("words") and match word(s) exactly
      (supports case-sensitive reliably, including non-ASCII).
    - whole_word=False: use page.search_for(query) (fast, multi-line, but
      case-insensitive for ASCII), then filter by exact-case using get_textbox()
      if case_sensitive=True.

    Notes:
    - Page.search_for() is case-insensitive for ASCII and does not support regex.
      See PyMuPDF docs.
    """
    query = (opts.query or "").strip()
    if not query:
        raise ValueError("query must be non-empty")

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_numbers = _resolve_pages(doc.page_count, opts.pages)
        rects: list[RedactionRect] = []

        for pno in page_numbers:
            page = doc.load_page(pno)
            if opts.whole_word:
                rects.extend(
                    _find_whole_word(
                        page,
                        pno,
                        query,
                        opts.case_sensitive,
                        opts.sort_words,
                    )
                )
            else:
                rects.extend(
                    _find_substring_like(
                        page,
                        pno,
                        query,
                        opts.case_sensitive,
                    )
                )

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


def _find_whole_word(
    page: pymupdf.Page,
    pno: int,
    query: str,
    case_sensitive: bool,
    sort_words: bool,
) -> list[RedactionRect]:
    words = page.get_text("words", sort=sort_words)
    tokens = query.split()

    if len(tokens) == 1:
        token = tokens[0]
        out: list[RedactionRect] = []
        for w in words:
            x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
            if _eq(text, token, case_sensitive):
                out.append(
                    RedactionRect(
                        page=pno,
                        x0=float(x0),
                        y0=float(y0),
                        x1=float(x1),
                        y1=float(y1),
                    )
                )
        return out

    # Multi-word phrase match: look for consecutive words matching tokens.
    # This is intentionally simple (sufficient for "exact search" step).
    norm_tokens = [t if case_sensitive else t.lower() for t in tokens]
    norm_words = [w[4] if case_sensitive else str(w[4]).lower() for w in words]

    out: list[RedactionRect] = []
    n = len(norm_tokens)
    i = 0
    while i <= len(words) - n:
        if norm_words[i : i + n] == norm_tokens:
            xs0 = [float(words[j][0]) for j in range(i, i + n)]
            ys0 = [float(words[j][1]) for j in range(i, i + n)]
            xs1 = [float(words[j][2]) for j in range(i, i + n)]
            ys1 = [float(words[j][3]) for j in range(i, i + n)]
            out.append(
                RedactionRect(
                    page=pno,
                    x0=min(xs0),
                    y0=min(ys0),
                    x1=max(xs1),
                    y1=max(ys1),
                )
            )
            i += n
        else:
            i += 1

    return out


def _rect_to_model(pno: int, r: pymupdf.Rect) -> RedactionRect:
    return RedactionRect(page=pno, x0=float(r.x0), y0=float(r.y0), x1=float(r.x1), y1=float(r.y1))


def _eq(a: str, b: str, case_sensitive: bool) -> bool:
    if case_sensitive:
        return a == b
    return a.lower() == b.lower()


def _collapse_ws(s: str) -> str:
    # Collapse all whitespace (spaces/newlines/tabs) into single spaces
    return " ".join((s or "").split())
