from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import pymupdf
import pypdf

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


# --------------------------------------------------------------------------
# Extraction : deux moteurs, pas un
#
# L'audit relisait la sortie avec PyMuPDF, c'est-à-dire la bibliothèque qui
# venait de la caviarder. Un angle mort d'extraction faisait donc rater la cible
# au moteur *et* au contrôle : deux échecs corrélés par construction, ce qui est
# la pire propriété possible pour une vérification.
#
# `pypdf` est pur Python, donc sans conséquence sur l'empaquetage figé. Les deux
# moteurs lisent, et une correspondance trouvée par l'un suffit à faire échouer
# l'export. Sur les quinze fixtures, quatorze extractions sont identiques au
# caractère près ; la quinzième, le texte pivoté, diffère d'une espace. C'est
# précisément là que le désaccord est utile.
# --------------------------------------------------------------------------

_PRIMARY_ENGINE = "pymupdf"


def _extract_pages_pymupdf(pdf_bytes: bytes) -> list[str]:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        return [doc.load_page(i).get_text("text") or "" for i in range(doc.page_count)]
    finally:
        doc.close()


def _extract_pages_pypdf(pdf_bytes: bytes) -> list[str]:
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return [(page.extract_text() or "") for page in reader.pages]


_EXTRACTORS: list[tuple[str, Any]] = [
    (_PRIMARY_ENGINE, _extract_pages_pymupdf),
    ("pypdf", _extract_pages_pypdf),
]


def audit_pdf_text(
    pdf_bytes: bytes, opts: AuditOptions, *, budget: RegexBudget | None = None
) -> dict[str, Any]:
    """Rejoue `opts` sur le texte extrait de chaque page et rend un rapport.

    Implémentation unique : le pipeline s'en servait via une copie locale qui
    avait divergé sur deux points — elle ne respectait pas exactement le
    plafond `max_total_matches`, et son rapport omettait `ignore_accents`.
    Une copie qu'aucun test ne couvre finit toujours par dériver.
    """
    if not pdf_bytes:
        raise ValueError("Empty PDF bytes")
    if not opts.patterns:
        raise ValueError("audit.patterns must be non-empty")

    matches: list[dict[str, Any]] = []
    matched_pages: set[int] = set()
    total_matches = 0

    pages_by_engine: dict[str, list[str]] = {}
    engine_status: dict[str, str] = {}

    for engine, extract in _EXTRACTORS:
        try:
            pages_by_engine[engine] = extract(pdf_bytes)
            engine_status[engine] = "ok"
        except Exception as e:  # noqa: BLE001 - un moteur muet ne doit pas masquer l'autre
            engine_status[engine] = f"failed: {type(e).__name__}"

    if not pages_by_engine:
        raise ValueError("no text extractor could read the output PDF")

    page_count_max = max(len(v) for v in pages_by_engine.values())

    for page_index in range(page_count_max):
        page_number = page_index + 1

        # Union par (motif, rang de l'occurrence) : si un moteur voit trois « Dupont »
        # et l'autre deux, on en retient trois. Le désaccord penche vers le signalement.
        best: dict[tuple[str, int], dict[str, Any]] = {}
        seen_by: dict[tuple[str, int], list[str]] = {}

        for engine, pages in pages_by_engine.items():
            if page_index >= len(pages):
                continue
            text = pages[page_index] or ""
            if not text:
                continue

            found, _ = audit_text(text, opts, page_number=page_number, budget=budget)

            rank: dict[str, int] = {}
            for m in found:
                pat = str(m["pattern"])
                key = (pat, rank.get(pat, 0))
                rank[pat] = rank.get(pat, 0) + 1
                seen_by.setdefault(key, []).append(engine)
                # On garde la variante PyMuPDF quand elle existe : c'est celle dont les
                # offsets s'alignent sur la géométrie du moteur de caviardage.
                if key not in best or engine == _PRIMARY_ENGINE:
                    best[key] = m

        if not best:
            continue

        page_matches = [
            {**best[k], "seen_by": sorted(seen_by[k])}
            for k in sorted(best, key=lambda k: (k[0], k[1]))
        ]
        page_matches = page_matches[: opts.max_matches_per_page]

        matched_pages.add(page_number)

        remaining = opts.max_total_matches - total_matches
        if remaining <= 0:
            break
        if len(page_matches) > remaining:
            page_matches = page_matches[:remaining]

        matches.extend(page_matches)
        total_matches += len(page_matches)

        if total_matches >= opts.max_total_matches:
            break

    return {
        "status": "pass" if total_matches == 0 else "fail",
        "total_matches": total_matches,
        "matched_pages": sorted(matched_pages),
        "extractors": engine_status,
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
