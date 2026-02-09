from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pymupdf

from app.audit import AuditOptions, audit_text, build_audit_for_search
from app.multiline_regex_engine import find_redaction_rectangles_by_regex
from app.presets import find_redaction_rectangles_for_presets
from app.redaction import RedactionRect, redact_pdf_by_rectangles
from app.search import SearchOptions, find_redaction_rectangles


@dataclass(frozen=True)
class RedactionOptions:
    apply_images: bool = False
    apply_graphics: bool = False
    sanitize_metadata: bool = False
    remove_annotations: bool = False
    remove_attachments: bool = False


@dataclass(frozen=True)
class SearchRequest:
    query: str
    case_sensitive: bool = False
    whole_word: bool = False
    pages: Sequence[int] | None = None


@dataclass(frozen=True)
class RegexRequest:
    patterns: list[str]
    case_sensitive: bool = False
    multiline: bool = False
    pages: Sequence[int] | None = None


@dataclass(frozen=True)
class PresetsRequest:
    presets: list[str]
    pages: Sequence[int] | None = None


@dataclass(frozen=True)
class PlanResult:
    manual: list[RedactionRect]
    search: list[RedactionRect]
    regex: list[RedactionRect]
    presets: list[RedactionRect]
    all_rects: list[RedactionRect]


def _dedupe_rects(rects: list[RedactionRect]) -> list[RedactionRect]:
    seen: set[tuple[int, float, float, float, float]] = set()
    out: list[RedactionRect] = []
    for r in rects:
        k = (int(r.page), round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2))
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def plan_redactions(
    pdf_bytes: bytes,
    *,
    manual_rects: list[RedactionRect] | None = None,
    search: SearchRequest | None = None,
    regex: RegexRequest | None = None,
    presets: PresetsRequest | None = None,
) -> PlanResult:
    if not pdf_bytes:
        raise ValueError("Empty PDF bytes")

    manual_out = list(manual_rects or [])

    search_rects: list[RedactionRect] = []
    regex_rects: list[RedactionRect] = []
    presets_rects: list[RedactionRect] = []

    if search is not None:
        search_rects = find_redaction_rectangles(
            pdf_bytes,
            SearchOptions(
                query=search.query,
                case_sensitive=search.case_sensitive,
                whole_word=search.whole_word,
                pages=search.pages,
            ),
        )

    if regex is not None:
        regex_rects = find_redaction_rectangles_by_regex(
            pdf_bytes,
            regex.patterns,
            case_sensitive=regex.case_sensitive,
            pages=regex.pages,
            multiline=regex.multiline,
        )

    if presets is not None:
        presets_rects = find_redaction_rectangles_for_presets(
            pdf_bytes,
            presets.presets,
            pages=presets.pages,
        )

    all_rects = _dedupe_rects(manual_out + search_rects + regex_rects + presets_rects)

    return PlanResult(
        manual=manual_out,
        search=search_rects,
        regex=regex_rects,
        presets=presets_rects,
        all_rects=all_rects,
    )


def apply_plan(pdf_bytes: bytes, plan: PlanResult, *, options: RedactionOptions) -> bytes:
    return redact_pdf_by_rectangles(
        pdf_bytes,
        plan.all_rects,
        apply_images=options.apply_images,
        apply_graphics=options.apply_graphics,
        sanitize_metadata=options.sanitize_metadata,
        remove_annotations=options.remove_annotations,
        remove_attachments=options.remove_attachments,
    )


def _presets_internal_audit(out_pdf: bytes, *, presets: PresetsRequest) -> dict[str, Any] | None:
    """
    Internal presets audit: rerun presets detection on OUT PDF.
    If leaks remain -> return a structured fail report, else None.
    """
    leaks_by_preset: dict[str, list[RedactionRect]] = {}
    total = 0
    matched_pages: set[int] = set()

    for p in presets.presets:
        rects = find_redaction_rectangles_for_presets(out_pdf, [p], pages=presets.pages)
        leaks_by_preset[p] = rects
        total += len(rects)
        matched_pages.update((r.page + 1) for r in rects)  # 1-based

    if total == 0:
        return None

    matches: list[dict[str, Any]] = []
    doc = pymupdf.open(stream=out_pdf, filetype="pdf")
    try:
        for preset_key, rects in leaks_by_preset.items():
            for r in rects:
                page = doc[r.page]
                rect = pymupdf.Rect(r.x0, r.y0, r.x1, r.y1)
                snippet = (page.get_textbox(rect) or "").strip()
                matches.append(
                    {
                        "preset": preset_key,
                        "page": r.page + 1,
                        "rect": {"x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1},
                        "snippet": snippet,
                    }
                )
    finally:
        doc.close()

    return {
        "status": "fail",
        "total_matches": total,
        "matched_pages": sorted(matched_pages),
        "options": {
            "mode": "presets_internal",
            "pages": list(presets.pages) if presets.pages else None
        },
        "presets": presets.presets,
        "matches": matches,
    }


def audit_plan(
    out_pdf: bytes,
    *,
    search: SearchRequest | None = None,
    regex: RegexRequest | None = None,
    presets: PresetsRequest | None = None,
    extra_audit: AuditOptions | None = None,
) -> dict[str, Any]:
    """
    Run coherent audits for all components that were requested.
    Returns either:
      - {"status":"pass", ...}  (composite pass report)
      - {"status":"fail", "components_failed":[...], "components":{...}} (composite fail)
    """
    failures: dict[str, Any] = {}

    # Search internal audit (coherent with whole_word / case_sensitive)
    if search is not None:
        s_opts = build_audit_for_search(
            query=search.query,
            case_sensitive=search.case_sensitive,
            whole_word=search.whole_word,
        )
        report = _audit_pdf_text(out_pdf, s_opts)
        if report["status"] != "pass":
            failures["search"] = report

    # Regex audit (coherent: same patterns)
    if regex is not None:
        r_opts = AuditOptions(
                        patterns=regex.patterns,
                        regex=True,
                        case_sensitive=regex.case_sensitive
                    )
        report = _audit_pdf_text(out_pdf, r_opts)
        if report["status"] != "pass":
            failures["regex"] = report

    # Presets internal audit
    if presets is not None:
        leak_report = _presets_internal_audit(out_pdf, presets=presets)
        if leak_report is not None:
            failures["presets"] = leak_report

    # Extra audit (optional banlist)
    if extra_audit is not None:
        report = _audit_pdf_text(out_pdf, extra_audit)
        if report["status"] != "pass":
            failures["audit"] = report

    if failures:
        return {
            "status": "fail",
            "components_failed": sorted(failures.keys()),
            "components": failures,
        }

    return {
        "status": "pass",
        "total_matches": 0,
        "matched_pages": [],
        "options": {"mode": "apply_combined"},
        "components": {},
    }


def _audit_pdf_text(pdf_bytes: bytes, opts: AuditOptions) -> dict[str, Any]:
    """
    A lightweight audit runner (page loop + audit_text) that returns the same report shape
    as app.audit.audit_pdf_text used to.
    We keep this here so the pipeline can produce composite reports without depending
    on HTTP-layer behavior.
    """
    if not opts.patterns:
        raise ValueError("audit.patterns must be non-empty")

    matches: list[dict[str, Any]] = []
    matched_pages: set[int] = set()
    total_matches = 0

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            text = page.get_text("text") or ""
            page_no = page_index + 1  # 1-based

            page_matches, page_total = audit_text(text, opts, page_number=page_no)
            if page_total:
                matches.extend(page_matches)
                matched_pages.add(page_no)
                total_matches += page_total

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
