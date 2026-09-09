from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pymupdf

from redactpdf.audit import build_whole_word_pattern, escape_literal, has_ligature_alternatives
from redactpdf.multiline_regex_engine import find_redaction_rectangles_by_regex
from redactpdf.redaction import RedactionRect
from redactpdf.regex_guard import RegexBudget


@dataclass(frozen=True)
class SearchOptions:
    query: str
    case_sensitive: bool = False
    whole_word: bool = False
    ignore_accents: bool = False
    pages: Sequence[int] | None = None


# Les trois chemins de recherche exacte doivent se comporter pareil face à une
# césure. Le chemin rapide (page.search_for) franchit déjà les fins de ligne ;
# sans ce drapeau, les deux chemins passant par le moteur regex ne le faisaient
# pas, et une requête multi-mots coupée en fin de ligne devenait introuvable —
# avec whole_word un export refusé (l'audit voyait ce que le moteur ratait), avec
# ignore_accents un export accepté laissant la donnée en clair.
# La fusion reste contrainte géométriquement (recouvrement en x, écart vertical
# maximal), ce qui continue d'exclure les fusions inter-colonnes : fixture 009.
_MULTILINE_SEARCH = True


def _build_substring_pattern(query: str) -> str:
    """
    Substring-like search expressed as regex, best-effort:
    - For multi-token queries, allow flexible whitespace (\\s+)
    - For single token, use escaped literal.
    """
    q = (query or "").strip()
    tokens = [t for t in q.split() if t]
    if not tokens:
        raise ValueError("query must be non-empty")

    if len(tokens) == 1:
        return escape_literal(tokens[0])
    return r"\s+".join(escape_literal(t) for t in tokens)


def find_redaction_rectangles(
    pdf_bytes: bytes, opts: SearchOptions, *, budget: RegexBudget | None = None
) -> list[RedactionRect]:
    query = (opts.query or "").strip()
    if not query:
        raise ValueError("query must be non-empty")

    # whole_word=True: keep existing semantics (boundary-aware regex)
    if opts.whole_word:
        pattern = build_whole_word_pattern(query)
        return find_redaction_rectangles_by_regex(
            pdf_bytes=pdf_bytes,
            patterns=[pattern],
            case_sensitive=opts.case_sensitive,
            pages=opts.pages,
            multiline=_MULTILINE_SEARCH,
            ignore_accents=opts.ignore_accents,
            budget=budget,
        )

    # Idem quand la requête contient une suite de lettres qu'un glyphe unique peut
    # porter : `page.search_for` cherche une chaîne, il ne sait pas exprimer
    # « ffi ou ﬃ ». Sans ce détour, le chemin rapide ratait « Griffith » écrit
    # « Griﬃth » en silence, et l'audit aussi, puisqu'il cherche la même chose.
    if opts.ignore_accents or has_ligature_alternatives(query):
        pattern = _build_substring_pattern(query)
        return find_redaction_rectangles_by_regex(
            pdf_bytes=pdf_bytes,
            patterns=[pattern],
            case_sensitive=opts.case_sensitive,
            pages=opts.pages,
            multiline=_MULTILINE_SEARCH,
            ignore_accents=opts.ignore_accents,
            budget=budget,
        )

    # Default path (fast): page.search_for()
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_numbers = _resolve_pages(doc.page_count, opts.pages)
        rects: list[RedactionRect] = []

        for pno in page_numbers:
            page = doc.load_page(pno)
            rects.extend(_find_substring_like(page, pno, query, opts.case_sensitive))

        return rects
    finally:
        doc.close()


def _resolve_pages(page_count: int, pages: Sequence[int] | None) -> list[int]:
    if pages is None:
        return list(range(page_count))
    if len(pages) == 0:
        return list(range(page_count))

    out: list[int] = []
    for p in pages:
        if p < 0 or p >= page_count:
            raise ValueError(f"Invalid page index {p}. Must be in [0, {page_count - 1}].")
        out.append(int(p))

    seen: set[int] = set()
    unique: list[int] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _quad_is_horizontal(quad: pymupdf.Quad) -> bool:
    """Le côté supérieur du quadrilatère est-il horizontal ?

    `search_for(quads=True)` rend la géométrie réelle de la correspondance et
    non son enveloppe : c'est ce qui permet de savoir si le texte est pivoté,
    information que le rectangle englobant a déjà perdue.
    """
    return abs(float(quad.ur.y) - float(quad.ul.y)) <= 1e-3


def _find_substring_like(
    page: pymupdf.Page,
    pno: int,
    query: str,
    case_sensitive: bool,
) -> list[RedactionRect]:
    candidates = page.search_for(query, quads=True)

    if not case_sensitive:
        return [_quad_to_model(pno, q) for q in candidates]

    needle = _collapse_ws(query)
    out: list[RedactionRect] = []
    for q in candidates:
        boxed = page.get_textbox(q.rect)
        hay = _collapse_ws(boxed)
        if needle in hay:
            out.append(_quad_to_model(pno, q))
    return out


def _quad_to_model(pno: int, quad: pymupdf.Quad) -> RedactionRect:
    r = quad.rect
    return RedactionRect(
        page=pno,
        x0=float(r.x0),
        y0=float(r.y0),
        x1=float(r.x1),
        y1=float(r.y1),
        from_horizontal_text=_quad_is_horizontal(quad),
    )


def _collapse_ws(s: str) -> str:
    return " ".join((s or "").split())
