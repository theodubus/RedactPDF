# backend/app/regex_engine.py
from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

import pymupdf  # PyMuPDF

from .redaction import RedactionRect


def _fold_keep_len(s: str) -> str:
    """
    Accent folding that preserves length 1:1 (critical for span->rect mapping).
    """
    out: list[str] = []
    for ch in s or "":
        decomp = unicodedata.normalize("NFKD", ch)
        base = ""
        for c in decomp:
            if unicodedata.combining(c):
                continue
            base = c
            break
        out.append(base if base else ch)
    return "".join(out)


def _fold_regex_pattern_best_effort(pattern: str) -> str:
    """
    Best-effort folding of literal characters in a regex pattern.

    - Preserves escapes (\\d, \\w, \\s, etc.)
    - Folds literal letters outside/inside character classes
    - Keeps length stable per character
    """
    p = pattern or ""
    out: list[str] = []
    escaped = False
    in_class = False

    for ch in p:
        if escaped:
            out.append(ch)
            escaped = False
            continue

        if ch == "\\":
            out.append(ch)
            escaped = True
            continue

        if ch == "[":
            in_class = True
            out.append(ch)
            continue

        if ch == "]" and in_class:
            in_class = False
            out.append(ch)
            continue

        out.append(_fold_keep_len(ch))

    return "".join(out)


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


def _compile_patterns(
    patterns: Sequence[str],
    *,
    case_sensitive: bool,
    ignore_accents: bool,
) -> list[re.Pattern[str]]:
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled: list[re.Pattern[str]] = []
    for pat in patterns:
        src = _fold_regex_pattern_best_effort(pat) if ignore_accents else pat
        try:
            compiled.append(re.compile(src, flags))
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
    line_words: list[tuple],
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
    ignore_accents: bool = False,
    max_hits: int = 10_000,
) -> list[RegexHit]:
    """
    Find regex matches on each line (mono-line engine) and map each match to a union rect of
    words overlapping the match span.

    Returns detailed hits (pattern + matched text), useful for post-filters (phone/Luhn).
    """
    pat_list = _normalize_patterns(patterns)
    compiled = _compile_patterns(
                            pat_list,
                            case_sensitive=case_sensitive,
                            ignore_accents=ignore_accents
                        )

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

                match_text = _fold_keep_len(line_text) if ignore_accents else line_text

                for pat, pat_src in zip(compiled, pat_list, strict=True):
                    for m in pat.finditer(match_text):
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

                        # indices are stable thanks to length-preserving fold
                        hits.append(
                            RegexHit(
                                page=page_index,
                                pattern=pat_src,
                                match=line_text[s:e],
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
    ignore_accents: bool = False,
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
        ignore_accents=ignore_accents,
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
