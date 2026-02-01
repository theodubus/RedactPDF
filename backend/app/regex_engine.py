from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

import pymupdf  # PyMuPDF

from .redaction import RedactionRect


@dataclass(frozen=True)
class RegexHit:
    """Internal representation of a regex match mapped to a PDF rectangle."""

    page: int
    pattern: str
    match: str
    rect: RedactionRect


def _normalize_patterns(patterns: str | Sequence[str]) -> list[str]:
    if isinstance(patterns, str):
        pat_list = [patterns]
    else:
        pat_list = list(patterns)

    pat_list = [p for p in (p.strip() for p in pat_list) if p]
    if not pat_list:
        raise ValueError("patterns must contain at least one non-empty regex string")
    return pat_list


def _compile_patterns(patterns: Sequence[str], *, case_sensitive: bool) -> list[re.Pattern[str]]:
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled: list[re.Pattern[str]] = []
    for pat in patterns:
        try:
            compiled.append(re.compile(pat, flags))
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {pat!r}. {e}") from e
    return compiled


def _resolve_pages(doc: pymupdf.Document, pages: Sequence[int] | None) -> list[int]:
    n = doc.page_count
    if pages is None:
        return list(range(n))
    if not pages:
        return []
    resolved: list[int] = []
    for p in pages:
        if p < 0 or p >= n:
            raise ValueError(f"Invalid page index {p}. Document has {n} pages.")
        resolved.append(p)
    # keep user order but remove duplicates
    seen: set[int] = set()
    unique: list[int] = []
    for p in resolved:
        if p not in seen:
            unique.append(p)
            seen.add(p)
    return unique


def _group_words_by_line(words: list[tuple]) -> dict[tuple[int, int], list[tuple]]:
    """
    PyMuPDF words format: (x0, y0, x1, y1, word, block_no, line_no, word_no).
    We group by (block_no, line_no).
    """
    lines: dict[tuple[int, int], list[tuple]] = {}
    for w in words:
        if len(w) < 8:
            continue
        block_no = int(w[5])
        line_no = int(w[6])
        key = (block_no, line_no)
        lines.setdefault(key, []).append(w)
    return lines


def _build_line_text_and_spans(
    line_words: list[tuple]
) -> tuple[str, list[tuple[int, int, pymupdf.Rect]]]:
    """
    Returns:
      - line_text built by joining words with single spaces
      - spans: list of (start_idx, end_idx, rect) for each word in line_text
    """
    # sort by word_no first, then x0 as fallback
    line_words_sorted = sorted(line_words, key=lambda w: (int(w[7]), float(w[0])))

    parts: list[str] = []
    spans: list[tuple[int, int, pymupdf.Rect]] = []
    cursor = 0

    for i, w in enumerate(line_words_sorted):
        x0, y0, x1, y1, text = float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])

        if i > 0:
            parts.append(" ")
            cursor += 1

        start = cursor
        parts.append(text)
        cursor += len(text)
        end = cursor

        spans.append((start, end, pymupdf.Rect(x0, y0, x1, y1)))

    return "".join(parts), spans


def iter_regex_hits_by_line(
    pdf_bytes: bytes,
    patterns: str | Sequence[str],
    *,
    case_sensitive: bool,
    pages: Sequence[int] | None = None,
    max_hits: int = 10_000,
) -> list[RegexHit]:
    """
    Find regex matches on each line (mono-line engine) and map each match to a union rect of
    words overlapping the match span.

    Returns detailed hits (pattern + matched text), useful for post-filters (phone/Luhn).
    """
    pat_list = _normalize_patterns(patterns)
    compiled = _compile_patterns(pat_list, case_sensitive=case_sensitive)

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_indexes = _resolve_pages(doc, pages)
        hits: list[RegexHit] = []

        for page_index in page_indexes:
            page = doc.load_page(page_index)
            words = page.get_text("words") or []
            lines = _group_words_by_line(words)

            for _, line_words in lines.items():
                line_text, spans = _build_line_text_and_spans(line_words)
                if not line_text:
                    continue

                for pat, pat_src in zip(compiled, pat_list, strict=True):
                    for m in pat.finditer(line_text):
                        if len(hits) >= max_hits:
                            return hits

                        s, e = m.span()
                        if s == e:
                            continue

                        # union rect for words overlapped by match span
                        union_rect: pymupdf.Rect | None = None
                        for ws, we, rect in spans:
                            if e <= ws or s >= we:
                                continue
                            union_rect = rect if union_rect is None else union_rect | rect

                        if union_rect is None:
                            continue

                        hit_rect = RedactionRect(
                            page=page_index,
                            x0=float(union_rect.x0),
                            y0=float(union_rect.y0),
                            x1=float(union_rect.x1),
                            y1=float(union_rect.y1),
                        )
                        hits.append(
                            RegexHit(
                                page=page_index,
                                pattern=pat_src,
                                match=m.group(0),
                                rect=hit_rect,
                            )
                        )

        return hits
    finally:
        doc.close()


def find_redaction_rectangles_by_regex(
    pdf_bytes: bytes,
    patterns: str | Sequence[str],
    *,
    case_sensitive: bool,
    pages: Sequence[int] | None = None,
) -> list[RedactionRect]:
    """
    Public API: return rectangles for regex matches (mono-line).

    Deduplicates rectangles approximately to avoid applying identical redactions multiple times.
    """
    hits = iter_regex_hits_by_line(
        pdf_bytes,
        patterns,
        case_sensitive=case_sensitive,
        pages=pages,
    )

    # approximate dedupe (round coords) to keep stability
    seen: set[tuple[int, float, float, float, float]] = set()
    rects: list[RedactionRect] = []
    for h in hits:
        k = (
            h.rect.page,
            round(h.rect.x0, 2),
            round(h.rect.y0, 2),
            round(h.rect.x1, 2),
            round(h.rect.y1, 2),
        )
        if k in seen:
            continue
        seen.add(k)
        rects.append(h.rect)

    return rects
