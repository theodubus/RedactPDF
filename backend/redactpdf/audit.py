from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import pymupdf

from redactpdf.regex_guard import RegexBudget, compile_pattern
from redactpdf.regex_guard import finditer as guarded_finditer


@dataclass(frozen=True)
class AuditOptions:
    patterns: list[str]
    regex: bool
    case_sensitive: bool
    ignore_accents: bool = False
    max_total_matches: int = 200
    max_matches_per_page: int = 50


def _fold_keep_len(s: str) -> str:
    """
    Accent folding that preserves string length 1:1 (important for index-based spans).
    For each char, NFKD-decompose and keep the first non-combining codepoint.
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

    - Preserves escapes: \"\\d\", \"\\w\", \"\\s\", \"\\b\", etc.
    - Folds literal letters both outside and inside character classes.
    - Keeps length stable per folded character (see _fold_keep_len).
    """
    p = pattern or ""
    out: list[str] = []

    escaped = False
    in_class = False

    for ch in p:
        if escaped:
            # keep escape sequence as-is
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

        # Fold only literal characters (best effort).
        # For meta like '(' ')' '.' '*', folding is no-op anyway.
        out.append(_fold_keep_len(ch))

    return "".join(out)


def _make_snippet(text: str, start: int, end: int, radius: int = 30) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return text[left:right].replace("\n", "\\n")


def _strip_accents_keep_len(s: str) -> str:
    """
    Best-effort accent folding with length preservation.
    For each character:
      - NFKD decomposes accents (e + ◌́)
      - remove combining marks
      - if multiple base chars result (rare, ligatures), keep the first char
    This keeps indices stable enough for audit position reporting.
    """
    out: list[str] = []
    for ch in s:
        decomp = unicodedata.normalize("NFKD", ch)
        base = "".join(c for c in decomp if not unicodedata.combining(c))
        if not base:
            out.append(ch)
        else:
            out.append(base[0])
    return "".join(out)


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


def build_audit_for_search(
    *,
    query: str,
    case_sensitive: bool,
    whole_word: bool,
    ignore_accents: bool = False
) -> AuditOptions:
    q = (query or "").strip()
    if not q:
        raise ValueError("query must be non-empty")

    if whole_word:
        pat = build_whole_word_pattern(q)
        return AuditOptions(
            patterns=[pat],
            regex=True,
            case_sensitive=case_sensitive,
            ignore_accents=ignore_accents,
        )

    return AuditOptions(
        patterns=[q],
        regex=False,
        case_sensitive=case_sensitive,
        ignore_accents=ignore_accents,
    )


def audit_text(
    text: str,
    opts: AuditOptions,
    *,
    page_number: int,
    budget: RegexBudget | None = None,
) -> tuple[list[dict[str, Any]], int]:
    if not opts.patterns:
        raise ValueError("audit.patterns must be non-empty")

    matches: list[dict[str, Any]] = []
    if not text:
        return matches, 0

    src_text = text
    folded_text = _fold_keep_len(text) if opts.ignore_accents else text

    # Regex mode
    if opts.regex:
        # L'audit rejoue les motifs de l'utilisateur : il est exposé au même
        # retour arrière catastrophique que la phase de planification, et sur un
        # texte de page entier plutôt que ligne par ligne.
        budget = budget if budget is not None else RegexBudget()

        compiled: list[tuple[str, Any]] = []
        for pat in opts.patterns:
            cleaned = (pat or "").strip()
            if not cleaned:
                continue

            cleaned_for_rx = (
                _fold_regex_pattern_best_effort(cleaned) if opts.ignore_accents else cleaned
            )

            compiled.append(
                (cleaned, compile_pattern(cleaned_for_rx, ignore_case=not opts.case_sensitive))
            )

        per_page = 0
        for pat_src, rx in compiled:
            for m in guarded_finditer(rx, folded_text, budget):
                start, end = m.span()
                # indexes align with original text due to fold_keep_len
                matches.append(
                    {
                        "pattern": pat_src,
                        "page": page_number,
                        "match": src_text[start:end],
                        "start": start,
                        "end": end,
                        "snippet": _make_snippet(src_text, start, end),
                        # Le moteur travaille sur des lignes ; l'audit sur le texte
                        # de page aplati. Une correspondance qui contient un saut de
                        # ligne n'a donc pas pu être localisée géométriquement, et
                        # c'est la seule chose qui distingue ce cas d'une redaction
                        # qui aurait échoué à s'appliquer.
                        "spans_line_break": "\n" in src_text[start:end],
                    }
                )
                per_page += 1
                if per_page >= opts.max_matches_per_page:
                    return matches, per_page
        return matches, per_page

    # Substring mode
    hay0 = folded_text if opts.case_sensitive else folded_text.casefold()

    per_page = 0
    for pat in opts.patterns:
        needle_raw = (pat or "").strip()
        if not needle_raw:
            continue

        needle_src = _fold_keep_len(needle_raw) if opts.ignore_accents else needle_raw
        needle0 = needle_src if opts.case_sensitive else needle_src.casefold()

        start = 0
        while True:
            idx = hay0.find(needle0, start)
            if idx == -1:
                break
            end = idx + len(needle0)

            matches.append(
                {
                    "pattern": needle_raw,
                    "page": page_number,
                    "match": src_text[idx:end],
                    "start": idx,
                    "end": end,
                    "snippet": _make_snippet(src_text, idx, end),
                    "spans_line_break": "\n" in src_text[idx:end],
                }
            )

            per_page += 1
            if per_page >= opts.max_matches_per_page:
                return matches, per_page

            start = end  # non-overlapping

    return matches, per_page


def audit_pdf_text(pdf_bytes: bytes, opts: AuditOptions) -> dict[str, Any]:
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
            "ignore_accents": opts.ignore_accents,
            "max_total_matches": opts.max_total_matches,
            "max_matches_per_page": opts.max_matches_per_page,
        },
        "patterns": opts.patterns,
        "matches": matches,
    }
