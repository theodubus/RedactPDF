from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import pymupdf  # PyMuPDF

from app.redaction import RedactionRect


@dataclass(frozen=True)
class _Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block_no: int
    line_no: int
    word_no: int


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    word: _Word


@dataclass(frozen=True)
class _Line:
    page: int
    block_no: int
    line_no: int
    words: tuple[_Word, ...]
    text: str
    spans: tuple[_Span, ...]
    x0: float
    x1: float
    y0: float
    y1: float


@dataclass(frozen=True)
class RegexHit:
    page: int
    pattern: str
    match: str
    rects: tuple[RedactionRect, ...]
    kind: str  # "single-line" | "multiline"


def _compile_patterns(patterns: Sequence[str], case_sensitive: bool) -> list[re.Pattern[str]]:
    cleaned: list[str] = []
    for p in patterns:
        p2 = (p or "").strip()
        if not p2:
            continue
        cleaned.append(p2)

    if not cleaned:
        raise ValueError("No non-empty regex patterns provided.")

    flags = 0 if case_sensitive else re.IGNORECASE
    compiled: list[re.Pattern[str]] = []
    for p in cleaned:
        try:
            compiled.append(re.compile(p, flags=flags))
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {p!r}. {e}") from e
    return compiled


def _rect_union(words: Sequence[_Word]) -> tuple[float, float, float, float]:
    x0 = min(w.x0 for w in words)
    y0 = min(w.y0 for w in words)
    x1 = max(w.x1 for w in words)
    y1 = max(w.y1 for w in words)
    return (x0, y0, x1, y1)


def _overlap_ratio(a0: float, a1: float, b0: float, b1: float) -> float:
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    denom = min(max(1e-9, a1 - a0), max(1e-9, b1 - b0))
    return inter / denom


def _extract_lines(doc: pymupdf.Document, page_index: int) -> list[_Line]:
    page = doc[page_index]
    raw = page.get_text("words")  # (x0,y0,x1,y1, "word", block, line, word)
    words: list[_Word] = []
    for (x0, y0, x1, y1, text, bno, lno, wno) in raw:
        t = (text or "").strip()
        if not t:
            continue
        words.append(
            _Word(
                x0=float(x0),
                y0=float(y0),
                x1=float(x1),
                y1=float(y1),
                text=t,
                block_no=int(bno),
                line_no=int(lno),
                word_no=int(wno),
            )
        )

    groups: dict[tuple[int, int], list[_Word]] = {}
    for w in words:
        groups.setdefault((w.block_no, w.line_no), []).append(w)

    lines: list[_Line] = []
    for (bno, lno), ws in groups.items():
        ws_sorted = sorted(ws, key=lambda w: (w.word_no, w.x0, w.y0))

        parts: list[str] = []
        spans: list[_Span] = []
        cursor = 0
        for i, w in enumerate(ws_sorted):
            if i > 0:
                parts.append(" ")
                cursor += 1
            start = cursor
            parts.append(w.text)
            cursor += len(w.text)
            end = cursor
            spans.append(_Span(start=start, end=end, word=w))

        text = "".join(parts)
        x0, y0, x1, y1 = _rect_union(ws_sorted)

        lines.append(
            _Line(
                page=page_index,
                block_no=bno,
                line_no=lno,
                words=tuple(ws_sorted),
                text=text,
                spans=tuple(spans),
                x0=x0,
                x1=x1,
                y0=y0,
                y1=y1,
            )
        )

    # Sort by top-to-bottom, then left-to-right
    lines.sort(key=lambda ln: (ln.y0, ln.x0, ln.block_no, ln.line_no))
    return lines


def _spans_overlapping(spans: Sequence[_Span], start: int, end: int) -> list[_Word]:
    hit_words: list[_Word] = []
    for sp in spans:
        if sp.end <= start:
            continue
        if sp.start >= end:
            continue
        hit_words.append(sp.word)
    return hit_words


def _dedup_rects(rects: list[RedactionRect], ndigits: int = 2) -> list[RedactionRect]:
    seen: set[tuple[int, float, float, float, float]] = set()
    out: list[RedactionRect] = []
    for r in rects:
        key = (
            r.page,
            round(r.x0, ndigits),
            round(r.y0, ndigits),
            round(r.x1, ndigits),
            round(r.y1, ndigits),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _find_next_line_candidate(
    lines: Sequence[_Line],
    idx: int,
    *,
    max_vertical_gap: float,
    min_x_overlap_ratio: float,
) -> _Line | None:
    """
    Find the best 'next line' for lines[idx], using geometric heuristics:
    - must be below the current line (b.y0 > a.y0)
    - must be close vertically (gap <= max_vertical_gap)
    - must overlap in x by at least min_x_overlap_ratio (prevents cross-column merges)
    Choose the candidate with smallest vertical gap.
    """
    a = lines[idx]
    best: _Line | None = None
    best_gap = float("inf")

    for j in range(idx + 1, len(lines)):
        b = lines[j]

        # only consider lines below (avoid same-baseline / cross-column trap where y is identical)
        if b.y0 <= a.y0 + 1e-6:
            continue

        # vertical gap between baselines (approx)
        gap = b.y0 - a.y1
        if gap < -1e-6:
            # overlapping boxes; still allow but treat gap as 0 (rare)
            gap = 0.0

        if gap > max_vertical_gap:
            # since lines are sorted by y0, once we're far below we can stop
            if b.y0 - a.y0 > max_vertical_gap + 10.0:
                break
            continue

        if _overlap_ratio(a.x0, a.x1, b.x0, b.x1) < min_x_overlap_ratio:
            continue

        if gap < best_gap:
            best_gap = gap
            best = b

    return best


def iter_regex_hits(
    pdf_bytes: bytes,
    patterns: Sequence[str],
    *,
    case_sensitive: bool,
    pages: Sequence[int] | None = None,
    multiline: bool = False,
    joiners: Sequence[str] = ("\n", " "),
    min_x_overlap_ratio: float = 0.25,
    max_vertical_gap: float = 18.0,
) -> Iterator[RegexHit]:
    """
    Regex -> hits with rectangles.

    - Single-line matching is always performed.
    - If multiline=True: also matches on (line N + joiner + next_line) where next_line
      is chosen by geometric heuristics (not by PyMuPDF block_no).
    - Returns rectangles per involved line (safer than one large rectangle across both lines).
    """
    compiled = _compile_patterns(patterns, case_sensitive=case_sensitive)

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_indices = list(range(len(doc))) if pages is None else list(pages)
        for pno in page_indices:
            if pno < 0 or pno >= len(doc):
                raise ValueError(f"Invalid page index: {pno}")

            lines = _extract_lines(doc, pno)

            # Single-line hits
            for ln in lines:
                for pat in compiled:
                    for m in pat.finditer(ln.text):
                        words = _spans_overlapping(ln.spans, m.start(), m.end())
                        if not words:
                            continue
                        x0, y0, x1, y1 = _rect_union(words)
                        rect = RedactionRect(page=pno, x0=x0, y0=y0, x1=x1, y1=y1)
                        yield RegexHit(
                            page=pno,
                            pattern=pat.pattern,
                            match=m.group(0),
                            rects=(rect,),
                            kind="single-line",
                        )

            if not multiline:
                continue

            # Multiline: for each line, pair with the best geometric "next line"
            for i, a in enumerate(lines):
                b = _find_next_line_candidate(
                    lines,
                    i,
                    max_vertical_gap=max_vertical_gap,
                    min_x_overlap_ratio=min_x_overlap_ratio,
                )
                if b is None:
                    continue

                for joiner in joiners:
                    combined = a.text + joiner + b.text
                    offset_b = len(a.text) + len(joiner)

                    for pat in compiled:
                        for m in pat.finditer(combined):
                            # keep only matches crossing the boundary
                            if m.end() <= len(a.text) or m.start() >= offset_b:
                                continue

                            words_a = _spans_overlapping(
                                a.spans,
                                m.start(),
                                min(m.end(), len(a.text)),
                            )
                            words_b = _spans_overlapping(
                                b.spans,
                                max(0, m.start() - offset_b),
                                max(0, m.end() - offset_b),
                            )

                            rects: list[RedactionRect] = []
                            if words_a:
                                x0, y0, x1, y1 = _rect_union(words_a)
                                rects.append(RedactionRect(page=pno, x0=x0, y0=y0, x1=x1, y1=y1))
                            if words_b:
                                x0, y0, x1, y1 = _rect_union(words_b)
                                rects.append(RedactionRect(page=pno, x0=x0, y0=y0, x1=x1, y1=y1))

                            if not rects:
                                continue

                            yield RegexHit(
                                page=pno,
                                pattern=pat.pattern,
                                match=m.group(0),
                                rects=tuple(rects),
                                kind="multiline",
                            )
    finally:
        doc.close()


def find_redaction_rectangles_by_regex(
    pdf_bytes: bytes,
    patterns: Sequence[str],
    *,
    case_sensitive: bool,
    pages: Sequence[int] | None = None,
    multiline: bool = False,
) -> list[RedactionRect]:
    rects: list[RedactionRect] = []
    for hit in iter_regex_hits(
        pdf_bytes,
        patterns,
        case_sensitive=case_sensitive,
        pages=pages,
        multiline=multiline,
    ):
        rects.extend(list(hit.rects))
    return _dedup_rects(rects)
