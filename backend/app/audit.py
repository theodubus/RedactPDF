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
    snippet = text[left:right].replace("\n", "\\n")
    return snippet


def audit_pdf_text(pdf_bytes: bytes, opts: AuditOptions) -> dict[str, Any]:
    """
    Audit post-redaction : extrait le texte page par page et vérifie l'absence
    de patterns (regex ou chaîne).
    Retourne un report structuré.
    """
    if not opts.patterns:
        raise ValueError("audit.patterns must be non-empty")

    matches: list[dict[str, Any]] = []
    matched_pages: set[int] = set()
    total_matches = 0

    # Préparer les patterns
    compiled: list[tuple[str, re.Pattern[str]]] = []
    if opts.regex:
        flags = 0
        if not opts.case_sensitive:
            flags |= re.IGNORECASE
        for pat in opts.patterns:
            try:
                compiled.append((pat, re.compile(pat, flags)))
            except re.error as e:
                raise ValueError(f"invalid regex pattern: {pat}") from e

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            text = page.get_text("text") or ""

            if not text:
                continue

            if opts.regex:
                for pat, rx in compiled:
                    for m in rx.finditer(text):
                        start, end = m.span()
                        matches.append(
                            {
                                "pattern": pat,
                                "page": page_index + 1,  # 1-based for humans
                                "match": m.group(0),
                                "start": start,
                                "end": end,
                                "snippet": _make_snippet(text, start, end),
                            }
                        )
                        matched_pages.add(page_index + 1)
                        total_matches += 1
                        if total_matches >= opts.max_total_matches:
                            break
                    if total_matches >= opts.max_total_matches:
                        break
            else:
                # simple substring search
                hay = text if opts.case_sensitive else text.lower()
                for pat in opts.patterns:
                    needle = pat if opts.case_sensitive else pat.lower()
                    if not needle:
                        continue

                    start = 0
                    per_page = 0
                    while True:
                        idx = hay.find(needle, start)
                        if idx == -1:
                            break
                        end = idx + len(needle)
                        matches.append(
                            {
                                "pattern": pat,
                                "page": page_index + 1,
                                "match": text[idx:end],
                                "start": idx,
                                "end": end,
                                "snippet": _make_snippet(text, idx, end),
                            }
                        )
                        matched_pages.add(page_index + 1)
                        total_matches += 1
                        per_page += 1

                        if total_matches >= opts.max_total_matches:
                            break
                        if per_page >= opts.max_matches_per_page:
                            break

                        start = end  # continue after the match

                    if total_matches >= opts.max_total_matches:
                        break

            if total_matches >= opts.max_total_matches:
                break

    finally:
        doc.close()

    status = "pass" if total_matches == 0 else "fail"
    report: dict[str, Any] = {
        "status": status,
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
    return report
