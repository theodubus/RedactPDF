from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pymupdf


@dataclass(frozen=True)
class AuditOptions:
    patterns: list[str]
    regex: bool
    case_sensitive: bool
    max_total_matches: int = 200
    max_matches_per_page: int = 50


def _make_snippet(text: str, start: int, end: int, radius: int = 30) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return text[left:right].replace("\n", "\\n")


def build_whole_word_pattern(query: str) -> str:
    """
    Build a boundary-aware regex for a query:
      - punctuation like ',', '.', '@' are boundaries (based on \\w)
      - multi-token queries allow flexible whitespace (\\s+)

    Examples:
      "Dupont" -> (?<!\\w)Dupont(?!\\w)
      "Jean Dupont" -> (?<!\\w)Jean\\s+Dupont(?!\\w)
    """
    q = (query or "").strip()
    tokens = [t for t in q.split() if t]
    if not tokens:
        raise ValueError("query must be non-empty")

    if len(tokens) == 1:
        core = re.escape(tokens[0])
    else:
        core = r"\s+".join(re.escape(t) for t in tokens)

    return rf"(?<!\w){core}(?!\w)"


def build_audit_for_search(*, query: str, case_sensitive: bool, whole_word: bool) -> AuditOptions:
    """
    Build AuditOptions coherent with /redact/search semantics:

    - whole_word=False: substring audit on the raw query
    - whole_word=True: regex audit using the same boundary rule as the search implementation
    """
    q = (query or "").strip()
    if not q:
        raise ValueError("query must be non-empty")

    if whole_word:
        pat = build_whole_word_pattern(q)
        return AuditOptions(patterns=[pat], regex=True, case_sensitive=case_sensitive)

    return AuditOptions(patterns=[q], regex=False, case_sensitive=case_sensitive)


def audit_text(
    text: str,
    opts: AuditOptions,
    *,
    page_number: int
) -> tuple[list[dict[str, Any]], int]:
    """
    Audit a single page text and return (matches, match_count) for that page.

    - Applies per-page cap: opts.max_matches_per_page
    - Does NOT apply global cap (opts.max_total_matches) here;
    global cap is handled by audit_pdf_text().
    """
    if not opts.patterns:
        raise ValueError("audit.patterns must be non-empty")

    matches: list[dict[str, Any]] = []
    if not text:
        return matches, 0

    # Regex mode
    if opts.regex:
        flags = 0
        if not opts.case_sensitive:
            flags |= re.IGNORECASE

        compiled: list[tuple[str, re.Pattern[str]]] = []
        for pat in opts.patterns:
            cleaned = (pat or "").strip()
            if not cleaned:
                continue
            try:
                compiled.append((cleaned, re.compile(cleaned, flags)))
            except re.error as e:
                raise ValueError(f"invalid regex pattern: {cleaned}") from e

        per_page = 0
        for pat, rx in compiled:
            for m in rx.finditer(text):
                start, end = m.span()
                matches.append(
                    {
                        "pattern": pat,
                        "page": page_number,
                        "match": m.group(0),
                        "start": start,
                        "end": end,
                        "snippet": _make_snippet(text, start, end),
                    }
                )
                per_page += 1
                if per_page >= opts.max_matches_per_page:
                    return matches, per_page
        return matches, per_page

    # Substring mode
    hay = text if opts.case_sensitive else text.casefold()

    per_page = 0
    for pat in opts.patterns:
        needle_raw = (pat or "").strip()
        if not needle_raw:
            continue
        needle = needle_raw if opts.case_sensitive else needle_raw.casefold()

        start = 0
        while True:
            idx = hay.find(needle, start)
            if idx == -1:
                break
            end = idx + len(needle)

            matches.append(
                {
                    "pattern": needle_raw,
                    "page": page_number,
                    "match": text[idx:end],
                    "start": idx,
                    "end": end,
                    "snippet": _make_snippet(text, idx, end),
                }
            )

            per_page += 1
            if per_page >= opts.max_matches_per_page:
                return matches, per_page

            start = end  # non-overlapping

    return matches, per_page


def audit_pdf_text(
    pdf_bytes: bytes,
    opts: AuditOptions
) -> dict[str, Any]:
    """
    Audit post-redaction:
    - extracts text page by page with PyMuPDF
    - searches for patterns (regex or substring)
    - enforces:
        - global cap: opts.max_total_matches
        - per-page cap: opts.max_matches_per_page (handled in audit_text)

    Report format matches what your API already expects:
      {
        "status": "pass"|"fail",
        "total_matches": int,
        "matched_pages": [int...],   # 1-based page numbers
        "options": {...},
        "patterns": [...],
        "matches": [...]
      }
    """
    if not pdf_bytes:
        raise ValueError("Empty PDF bytes")
    if not opts.patterns:
        raise ValueError("audit.patterns must be non-empty")

    matches: list[dict[str, Any]] = []
    matched_pages: set[int] = set()
    total_matches = 0

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page_index in range(doc.page_count):
            page_number = page_index + 1
            page = doc.load_page(page_index)
            text = page.get_text("text") or ""
            if not text:
                continue

            page_matches, page_count = audit_text(text, opts, page_number=page_number)
            if page_count:
                matched_pages.add(page_number)

            # Respect global cap
            remaining = opts.max_total_matches - total_matches
            if remaining <= 0:
                break

            if len(page_matches) > remaining:
                page_matches = page_matches[:remaining]
                page_count = len(page_matches)

            matches.extend(page_matches)
            total_matches += page_count

            if total_matches >= opts.max_total_matches:
                break
    finally:
        doc.close()

    return {
        "status": "pass" if total_matches == 0 else "fail",
        "total_matches": total_matches,
        "matched_pages": sorted(matched_pages),
        "options": {
            "regex": opts.regex,
            "case_sensitive": opts.case_sensitive,
            "max_total_matches": opts.max_total_matches,
            "max_matches_per_page": opts.max_matches_per_page,
        },
        "patterns": opts.patterns,
        "matches": matches,
    }
