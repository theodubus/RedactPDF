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
    # Mêmes défauts que OptionsModel : sûrs, pas permissifs.
    image_mode: str = "pixels"
    apply_graphics: bool = True
    sanitize_metadata: bool = True
    remove_annotations: bool = True
    remove_attachments: bool = True


@dataclass(frozen=True)
class SearchRequest:
    query: str
    case_sensitive: bool = False
    whole_word: bool = False
    ignore_accents: bool = False
    pages: Sequence[int] | None = None


@dataclass(frozen=True)
class RegexRequest:
    patterns: list[str]
    case_sensitive: bool = False
    multiline: bool = False
    ignore_accents: bool = False
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
    full_page: list[RedactionRect]
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
    searches: Sequence[SearchRequest] | None = None,
    regexes: Sequence[RegexRequest] | None = None,
    presets: PresetsRequest | None = None,
    full_page_rects: list[RedactionRect] | None = None,
) -> PlanResult:
    if not pdf_bytes:
        raise ValueError("Empty PDF bytes")

    manual_out = list(manual_rects or [])
    full_page_out = list(full_page_rects or [])

    search_rects: list[RedactionRect] = []
    regex_rects: list[RedactionRect] = []
    presets_rects: list[RedactionRect] = []

    if searches:
        for s in searches:
            search_rects.extend(
                find_redaction_rectangles(
                    pdf_bytes,
                    SearchOptions(
                        query=s.query,
                        case_sensitive=s.case_sensitive,
                        whole_word=s.whole_word,
                        ignore_accents=s.ignore_accents,
                        pages=s.pages,
                    ),
                )
            )

    if regexes:
        for r in regexes:
            regex_rects.extend(
                find_redaction_rectangles_by_regex(
                    pdf_bytes,
                    r.patterns,
                    case_sensitive=r.case_sensitive,
                    pages=r.pages,
                    multiline=r.multiline,
                    ignore_accents=r.ignore_accents,
                )
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
        full_page=full_page_out,
        all_rects=all_rects,
    )


def apply_plan(pdf_bytes: bytes, plan: PlanResult, *, options: RedactionOptions) -> bytes:
    """
    Apply the plan in two passes when full-page rules exist:
      1. Strict pass on full-page rects (remove images + graphics, irrespective
         of the user's chosen image_mode). A page-wide rule is always meant to
         wipe everything.
      2. User-mode pass on every other rect.
    Sanitisation (metadata / annotations / attachments) runs on the final pass.
    """
    if plan.full_page:
        pdf_bytes = redact_pdf_by_rectangles(
            pdf_bytes,
            plan.full_page,
            image_mode="remove",
            apply_graphics=True,
            # Defer sanitisation to the second pass so it's applied once on the final PDF.
            sanitize_metadata=False,
            remove_annotations=False,
            remove_attachments=False,
        )

    return redact_pdf_by_rectangles(
        pdf_bytes,
        plan.all_rects,
        image_mode=options.image_mode,
        apply_graphics=options.apply_graphics,
        sanitize_metadata=options.sanitize_metadata,
        remove_annotations=options.remove_annotations,
        remove_attachments=options.remove_attachments,
    )


def presets_internal_audit(out_pdf: bytes, *, presets: PresetsRequest) -> dict[str, Any] | None:
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
    searches: Sequence[SearchRequest] | None = None,
    regexes: Sequence[RegexRequest] | None = None,
    presets: PresetsRequest | None = None,
    extra_audit: AuditOptions | None = None,
) -> dict[str, Any]:
    """
    Run coherent audits for all components that were requested.
    Supports multiple search and regex rules.
    """
    failures: dict[str, Any] = {}

    # --- Searches audit (cohérent avec whole_word / case_sensitive), par règle
    if searches:
        failed: list[dict[str, Any]] = []
        for idx, s in enumerate(searches):
            s_opts = build_audit_for_search(
                query=s.query,
                case_sensitive=s.case_sensitive,
                whole_word=s.whole_word,
                ignore_accents=s.ignore_accents,
            )
            report = _audit_pdf_text(out_pdf, s_opts)
            if report["status"] != "pass":
                failed.append(
                    {
                        "index": idx,
                        "query": s.query,
                        "case_sensitive": s.case_sensitive,
                        "whole_word": s.whole_word,
                        "pages": list(s.pages) if s.pages else None,
                        "report": report,
                    }
                )

        if failed:
            failures["searches"] = {
                "status": "fail",
                "rules_failed": len(failed),
                "rules_total": len(list(searches)),
                "failed": failed,
            }

    # --- Regex audit (cohérent : mêmes patterns), par règle
    if regexes:
        failed = []
        for idx, r in enumerate(regexes):
            r_opts = AuditOptions(
                patterns=r.patterns,
                regex=True,
                case_sensitive=r.case_sensitive,
                ignore_accents=r.ignore_accents,
            )
            report = _audit_pdf_text(out_pdf, r_opts)
            if report["status"] != "pass":
                failed.append(
                    {
                        "index": idx,
                        "patterns": r.patterns,
                        "case_sensitive": r.case_sensitive,
                        "multiline": r.multiline,
                        "pages": list(r.pages) if r.pages else None,
                        "report": report,
                    }
                )

        if failed:
            failures["regexes"] = {
                "status": "fail",
                "rules_failed": len(failed),
                "rules_total": len(list(regexes)),
                "failed": failed,
            }

    # --- Presets internal audit
    if presets is not None:
        leak_report = presets_internal_audit(out_pdf, presets=presets)
        if leak_report is not None:
            failures["presets"] = leak_report

    # --- Extra audit (optional banlist)
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
