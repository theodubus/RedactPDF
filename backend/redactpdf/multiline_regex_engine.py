# backend/app/multiline_regex_engine.py
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import pymupdf  # PyMuPDF

from redactpdf.redaction import RedactionRect


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
    Best-effort folding of literal characters in a regex pattern, without trying
    to fully parse regex grammar.

    - Preserves escapes (\\d, \\w, \\s, \\b, etc.)
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

        if unicodedata.combining(ch):
            # Ignore combining marks in patterns when ignore_accents is enabled
            continue
        out.append(_fold_keep_len(ch))


    return "".join(out)


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
class _CharBox:
    c: str
    rect: pymupdf.Rect
    # Vecteur d'écriture de la ligne d'origine : (1, 0) à l'horizontale,
    # (0, ±1) pivotée d'un quart de tour. Sert à deux choses, et les deux
    # comptent : savoir si la hauteur du rectangle est de la marge ou de la
    # ligne, et ordonner les glyphes dans le sens de la lecture.
    direction: tuple[float, float]

    @property
    def horizontal(self) -> bool:
        return abs(self.direction[1]) <= 1e-3


@dataclass(frozen=True)
class RegexHit:
    page: int
    pattern: str
    match: str
    rects: tuple[RedactionRect, ...]
    kind: str  # "single-line" | "multiline"


def _fold_text_and_map_indices(s: str) -> tuple[str, list[int]]:
    """
    Fold a string for accent-insensitive matching AND return a boundary map.

    Returns:
      - folded text (accents removed, combining marks removed)
      - boundaries map of length len(folded)+1 where map[i] is the index in the
        original string corresponding to boundary i in the folded string.

    Combining marks are absorbed into the preceding base-char cluster so that
    matches include them in the original span (better redaction coverage).
    """
    out: list[str] = []
    boundaries: list[int] = [0]

    i = 0
    n = len(s)
    while i < n:
        ch = s[i]

        # If we encounter a stray combining mark, attach it to the previous cluster.
        if unicodedata.combining(ch):
            boundaries[-1] = i + 1
            i += 1
            continue

        # Consume the whole grapheme cluster: base + trailing combining marks
        j = i + 1
        while j < n and unicodedata.combining(s[j]):
            j += 1

        # Fold the base char (1 output char)
        decomp = unicodedata.normalize("NFKD", ch)
        base = ""
        for c in decomp:
            if unicodedata.combining(c):
                continue
            base = c
            break

        out.append(base if base else ch)
        boundaries.append(j)
        i = j

    return "".join(out), boundaries


def _compile_patterns(
    patterns: Sequence[str],
    *,
    case_sensitive: bool,
    ignore_accents: bool,
) -> list[tuple[str, re.Pattern[str]]]:
    cleaned: list[str] = []
    for p in patterns:
        p2 = (p or "").strip()
        if not p2:
            continue
        cleaned.append(p2)

    if not cleaned:
        raise ValueError("No non-empty regex patterns provided.")

    flags = 0 if case_sensitive else re.IGNORECASE
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for p in cleaned:
        src = _fold_regex_pattern_best_effort(p) if ignore_accents else p
        try:
            compiled.append((p, re.compile(src, flags=flags)))
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
            gap = 0.0

        if gap > max_vertical_gap:
            if b.y0 - a.y0 > max_vertical_gap + 10.0:
                break
            continue

        if _overlap_ratio(a.x0, a.x1, b.x0, b.x1) < min_x_overlap_ratio:
            continue

        if gap < best_gap:
            best_gap = gap
            best = b

    return best


def _extract_page_chars(page: pymupdf.Page) -> list[_CharBox]:
    """
    Extract character boxes from rawdict (best available to support partial redaction).
    """
    raw: dict[str, Any] = page.get_text("rawdict") or {}
    out: list[_CharBox] = []

    for block in raw.get("blocks", []) or []:
        for line in block.get("lines", []) or []:
            # `dir` est le vecteur d'écriture de la ligne : (1, 0) à l'horizontale,
            # (0, ±1) pivotée d'un quart de tour. C'est la seule information qui
            # distingue « hauteur = marge autour des lettres » de « hauteur = la
            # ligne elle-même ».
            raw_dir = line.get("dir") or (1.0, 0.0)
            direction = (float(raw_dir[0]), float(raw_dir[1]))
            for span in line.get("spans", []) or []:
                for ch in span.get("chars", []) or []:
                    c = ch.get("c")
                    bbox = ch.get("bbox")
                    if not c or not bbox:
                        continue
                    try:
                        rect = pymupdf.Rect(bbox)
                    except Exception:
                        continue
                    out.append(_CharBox(c=str(c), rect=rect, direction=direction))

    # Stable ordering: top-to-bottom then left-to-right
    out.sort(key=lambda it: (round(it.rect.y0, 1), it.rect.x0, round(it.rect.y1, 1)))
    return out


def _rect_contains(outer: pymupdf.Rect, inner: pymupdf.Rect, tol: float = 0.75) -> bool:
    return (
        inner.x0 >= outer.x0 - tol
        and inner.y0 >= outer.y0 - tol
        and inner.x1 <= outer.x1 + tol
        and inner.y1 <= outer.y1 + tol
    )


def _rect_for_word_segment(
    page_chars: list[_CharBox],
    word: _Word,
    *,
    start_off: int,
    end_off: int,
) -> tuple[pymupdf.Rect, bool]:
    """
    Return a tight rect for a substring inside a single word, and whether that
    word is written horizontally.

    Falls back to full-word rect if we cannot reliably map chars. L'orientation
    est déduite des boîtes de glyphes : quand on ne peut pas les retrouver, on
    répond `False`, ce qui laisse le rectangle intact plutôt que de le resserrer
    à tort.
    """
    wrect = pymupdf.Rect(word.x0, word.y0, word.x1, word.y1)
    chars_here = [cb for cb in page_chars if _rect_contains(wrect, cb.rect)]
    horizontal = bool(chars_here) and all(cb.horizontal for cb in chars_here)

    if start_off <= 0 and end_off >= len(word.text):
        return wrect, horizontal

    if start_off < 0:
        start_off = 0
    if end_off > len(word.text):
        end_off = len(word.text)
    if end_off <= start_off:
        return wrect, horizontal

    candidates = list(chars_here)
    if not candidates:
        return wrect, horizontal

    # Ordonner les glyphes dans le SENS DE LA LECTURE, pas de gauche à droite.
    # Sur une ligne pivotée d'un quart de tour, tous les glyphes partagent le même
    # x0 : trier par x puis y les rend à l'envers, et le segment sélectionné
    # couvre alors les mauvais caractères -- « ,48 » devient « 84, », et un « 48 »
    # visé fait caviarder « 4, » en laissant le 8 en clair.
    dx, dy = candidates[0].direction
    candidates.sort(key=lambda cb: (cb.rect.x0 * dx + cb.rect.y0 * dy, cb.rect.x0, cb.rect.y0))

    # Keep only non-space chars for alignment.
    candidates_nospace = [cb for cb in candidates if cb.c.strip() != ""]
    if len(candidates_nospace) < len(word.text):
        # Not enough characters; fallback.
        return wrect, horizontal

    # Heuristic alignment: take the first len(word.text) chars in the word rect.
    aligned = candidates_nospace[: len(word.text)]

    # Select the segment
    seg = aligned[start_off:end_off]
    if not seg:
        return wrect, horizontal

    rect = seg[0].rect
    for cb in seg[1:]:
        rect = rect | cb.rect
    return rect, horizontal


def _rect_for_match_on_line(
    ln: _Line,
    page_chars: list[_CharBox],
    *,
    start: int,
    end: int,
) -> tuple[pymupdf.Rect, bool] | None:
    """
    Build a union rect for the match span on a given line, with partial-word support.

    Renvoie aussi l'orientation : le rectangle n'est déclaré horizontal que si
    *tous* les mots qu'il couvre le sont.
    """
    if end <= start:
        return None

    rect_union: pymupdf.Rect | None = None
    horizontal = True

    for sp in ln.spans:
        if sp.end <= start:
            continue
        if sp.start >= end:
            continue

        ov_start = max(start, sp.start)
        ov_end = min(end, sp.end)

        start_off = ov_start - sp.start
        end_off = ov_end - sp.start

        seg_rect, seg_horizontal = _rect_for_word_segment(
            page_chars, sp.word, start_off=start_off, end_off=end_off
        )
        horizontal = horizontal and seg_horizontal
        rect_union = seg_rect if rect_union is None else rect_union | seg_rect

    if rect_union is None:
        return None
    return rect_union, horizontal


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
    ignore_accents: bool = False,
) -> Iterator[RegexHit]:
    compiled = _compile_patterns(
        patterns,
        case_sensitive=case_sensitive,
        ignore_accents=ignore_accents,
    )

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_indices = list(range(len(doc))) if pages is None else list(pages)
        for pno in page_indices:
            if pno < 0 or pno >= len(doc):
                raise ValueError(f"Invalid page index: {pno}")

            page = doc[pno]
            page_chars = _extract_page_chars(page)
            lines = _extract_lines(doc, pno)

            def line_text_for_match(s: str) -> tuple[str, list[int]]:
                if not ignore_accents:
                    return s, list(range(len(s) + 1))
                return _fold_text_and_map_indices(s)


            # Single-line hits
            for ln in lines:
                ln_text_match, ln_map = line_text_for_match(ln.text)

                for pat_src, pat in compiled:
                    for m in pat.finditer(ln_text_match):
                        s, e = m.span()
                        orig_s = ln_map[s]
                        orig_e = ln_map[e]

                        found = _rect_for_match_on_line(ln, page_chars, start=orig_s, end=orig_e)
                        if found is None:
                            continue
                        rect, horizontal = found

                        yield RegexHit(
                            page=pno,
                            pattern=pat_src,
                            match=ln.text[orig_s:orig_e],

                            rects=(
                                RedactionRect(
                                    page=pno,
                                    x0=float(rect.x0),
                                    y0=float(rect.y0),
                                    x1=float(rect.x1),
                                    y1=float(rect.y1),
                                    from_horizontal_text=horizontal,
                                ),
                            ),
                            kind="single-line",
                        )

            if not multiline:
                continue

            # Multiline pairing via geometry
            for i, a in enumerate(lines):
                b = _find_next_line_candidate(
                    lines,
                    i,
                    max_vertical_gap=max_vertical_gap,
                    min_x_overlap_ratio=min_x_overlap_ratio,
                )
                if b is None:
                    continue

                a_match, a_map = line_text_for_match(a.text)
                b_match, b_map = line_text_for_match(b.text)

                for joiner in joiners:
                    combined = a_match + joiner + b_match
                    offset_b = len(a_match) + len(joiner)

                    for pat_src, pat in compiled:
                        for m in pat.finditer(combined):
                            s, e = m.span()

                            # keep only matches crossing the boundary
                            if e <= len(a_match) or s >= offset_b:
                                continue

                            # Span on A:
                            a_s = s
                            a_e = min(e, len(a_match))

                            b_s = max(0, s - offset_b)
                            b_e = max(0, e - offset_b)

                            orig_a_s = a_map[a_s]
                            orig_a_e = a_map[a_e]
                            orig_b_s = b_map[b_s]
                            orig_b_e = b_map[b_e]

                            rects: list[RedactionRect] = []

                            rect_a = _rect_for_match_on_line(
                                                a,
                                                page_chars,
                                                start=orig_a_s,
                                                end=orig_a_e
                                            )

                            if rect_a is not None:
                                ra, ra_horizontal = rect_a
                                rects.append(
                                    RedactionRect(
                                        page=pno,
                                        x0=float(ra.x0),
                                        y0=float(ra.y0),
                                        x1=float(ra.x1),
                                        y1=float(ra.y1),
                                        from_horizontal_text=ra_horizontal,
                                    )
                                )

                            rect_b = _rect_for_match_on_line(
                                                    b,
                                                    page_chars,
                                                    start=orig_b_s,
                                                    end=orig_b_e
                                                )
                            if rect_b is not None:
                                rb, rb_horizontal = rect_b
                                rects.append(
                                    RedactionRect(
                                        page=pno,
                                        x0=float(rb.x0),
                                        y0=float(rb.y0),
                                        x1=float(rb.x1),
                                        y1=float(rb.y1),
                                        from_horizontal_text=rb_horizontal,
                                    )
                                )

                            if not rects:
                                continue

                            # Build a boundary map for combined folded text
                            # -> original_combined indices
                            a_end = a_map[-1]
                            combined_map: list[int] = list(a_map)
                            for j in range(1, len(joiner) + 1):
                                combined_map.append(a_end + j)
                            for k in range(1, len(b_map)):
                                combined_map.append(a_end + len(joiner) + b_map[k])

                            original_combined = a.text + joiner + b.text
                            orig_s = combined_map[s]
                            orig_e = combined_map[e]
                            match_str = original_combined[orig_s:orig_e]

                            yield RegexHit(
                                page=pno,
                                pattern=pat_src,
                                match=match_str,
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
    ignore_accents: bool = False,
) -> list[RedactionRect]:
    rects: list[RedactionRect] = []
    for hit in iter_regex_hits(
        pdf_bytes,
        patterns,
        case_sensitive=case_sensitive,
        pages=pages,
        multiline=multiline,
        ignore_accents=ignore_accents,
    ):
        rects.extend(list(hit.rects))
    return _dedup_rects(rects)
