from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

import phonenumbers
import pymupdf  # PyMuPDF

from app.redaction import RedactionRect


# For numbers without a leading '+' we need a region hint.
# Default to FR but allow overriding through env var.
def _default_region() -> str:
    return os.getenv("REDACT_DEFAULT_REGION", "FR").upper()


@dataclass(frozen=True)
class PresetDefinition:
    key: str
    label: str
    description: str
    pattern: str
    flags: int = 0
    post_filter: Callable[[str], bool] | None = None


def _luhn_is_valid(number: str) -> bool:
    """Luhn checksum for credit-card-like numbers. Expects digits only."""
    if not number.isdigit():
        return False

    total = 0
    rev = number[::-1]
    for idx, ch in enumerate(rev):
        d = ord(ch) - ord("0")
        if idx % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _credit_card_post_filter(match_text: str) -> bool:
    """Reduce false positives: keep only plausible PANs (13..19) with valid Luhn."""
    digits = re.sub(r"\D+", "", match_text)
    if not (13 <= len(digits) <= 19):
        return False
    return _luhn_is_valid(digits)


_EXT_RX = re.compile(r"(?i)\b(?:ext\.?|extension|poste|x|#)\s*\d{1,6}\b")
_LEADING_00_RX = re.compile(r"^\s*00")


def _normalize_phone_candidate(s: str) -> str:
    """
    Normalize a phone candidate before parsing:
    - remove common extension tokens (ext, x, poste, #...)
    - convert leading 00... to +...
    - keep leading '+', strip other non-digits
    """
    s = s.strip()
    # Remove extension part (keep base number)
    s = _EXT_RX.sub("", s).strip()

    # Convert international prefix 00 -> +
    if _LEADING_00_RX.match(s):
        s = "+" + _LEADING_00_RX.sub("", s).lstrip()

    # Keep leading + if present, strip everything else to digits
    if s.startswith("+"):
        return "+" + re.sub(r"\D+", "", s[1:])
    return re.sub(r"\D+", "", s)


def _phone_post_filter(match_text: str) -> bool:
    """
    Validate phone candidates using phonenumbers (libphonenumber).

    Policy:
    - If candidate is in international form (+...), parse without region (unambiguous).
    - Else parse using DEFAULT_REGION (configurable via REDACT_DEFAULT_REGION env var).
    - Require is_possible_number AND is_valid_number to reduce false positives.

    Limitations:
    - Numbers without '+' depend on DEFAULT_REGION; this is unavoidable for generic parsing.
    - Mono-line only in v1; multi-line handled in a later step.
    """
    normalized = _normalize_phone_candidate(match_text)

    # quick length filter to avoid many false positives
    digits_only = normalized[1:] if normalized.startswith("+") else normalized
    if not digits_only.isdigit():
        return False
    if len(digits_only) < 7 or len(digits_only) > 15:
        return False

    try:
        if normalized.startswith("+"):
            num = phonenumbers.parse(normalized, None)
        else:
            # Parse national formats using default region hint
            num = phonenumbers.parse(normalized, _default_region())

        # Strong filtering: both possible and valid
        if not phonenumbers.is_possible_number(num):
            return False
        if not phonenumbers.is_valid_number(num):
            return False
        return True
    except phonenumbers.NumberParseException:
        return False

DEFAULT_REGION = _default_region()

# Presets v1: conservative and tested; mono-line matching by design.
_PRESETS: dict[str, PresetDefinition] = {
    "email": PresetDefinition(
        key="email",
        label="Email",
        description=(
            "Matches common email addresses. Limitations: may miss exotic cases; "
            "relies on text being extractable (OCR not handled)."
        ),
        pattern=r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        flags=re.IGNORECASE,
    ),
    "phone": PresetDefinition(
        key="phone",
        label="Phone (international, validated)",
        description=(
            "Heuristically extracts phone-like candidates (international/national forms, "
            "common separators) and validates them using libphonenumber (phonenumbers). "
            "Limitations: mono-line only in v1; numbers without '+' require a default region "
            f"(current DEFAULT_REGION={DEFAULT_REGION}). OCR not handled."
        ),
        # Candidate extraction regex (tolerant):
        # - optional leading +country or 00country
        # - allows parentheses and separators
        # - requires enough digits overall (via post_filter length + libphonenumber)
        #
        # Note: We keep it broad and rely on post_filter for robustness.
        pattern=r"\b(?:\+|00)?\s*(?:\d[\s().\-]?){6,20}\d\b",
        flags=0,
        post_filter=_phone_post_filter,
    ),
    "credit_card": PresetDefinition(
        key="credit_card",
        label="Credit card (Luhn-filtered)",
        description=(
            "Matches 13..19-digit sequences with spaces/hyphens and validates with Luhn. "
            "Limitations: may still match some non-card identifiers; mono-line only in v1."
        ),
        pattern=r"\b(?:\d[ -]*?){13,19}\b",
        flags=0,
        post_filter=_credit_card_post_filter,
    ),
}


def available_presets() -> list[str]:
    return sorted(_PRESETS.keys())


def _get_preset(preset: str) -> PresetDefinition:
    try:
        return _PRESETS[preset]
    except KeyError as exc:
        raise ValueError(
            f"Unknown preset '{preset}'. Available: {', '.join(available_presets())}"
        ) from exc


@dataclass(frozen=True)
class _WordSpan:
    rect: pymupdf.Rect
    text: str
    start: int
    end: int  # exclusive


def _group_words_by_line(
    page: pymupdf.Page,
) -> list[list[tuple[float, float, float, float, str, int, int, int]]]:
    """
    Return words grouped by (block_no, line_no) in stable order.
    Each word tuple is (x0, y0, x1, y1, word, block_no, line_no, word_no).
    """
    words = page.get_text("words")
    words_sorted = sorted(words, key=lambda w: (int(w[5]), int(w[6]), int(w[7])))
    grouped: dict[tuple[int, int], list[tuple[float, float, float, float, str, int, int, int]]] = {}

    for w in words_sorted:
        key = (int(w[5]), int(w[6]))
        grouped.setdefault(key, []).append(w)

    return [grouped[k] for k in sorted(grouped.keys())]


def _build_line_text_and_spans(
    line_words: list[tuple[float, float, float, float, str, int, int, int]],
) -> tuple[str, list[_WordSpan]]:
    """
    Join words with single spaces and track each word's character span.
    This is a heuristic mapping; it's sufficient for v1 mono-line presets.
    """
    parts: list[str] = []
    spans: list[_WordSpan] = []
    cursor = 0

    for idx, (x0, y0, x1, y1, word, *_rest) in enumerate(line_words):
        if idx > 0:
            parts.append(" ")
            cursor += 1

        parts.append(word)
        start = cursor
        cursor += len(word)
        end = cursor
        spans.append(_WordSpan(rect=pymupdf.Rect(x0, y0, x1, y1), text=word, start=start, end=end))

    return "".join(parts), spans


def _rect_union(spans: Iterable[_WordSpan]) -> pymupdf.Rect:
    spans_list = list(spans)
    if not spans_list:
        raise ValueError("Cannot build union rect from empty spans.")
    union = pymupdf.Rect(spans_list[0].rect)
    for s in spans_list[1:]:
        union |= s.rect
    return union


def find_redaction_rectangles_for_presets(
    pdf_bytes: bytes,
    presets: Sequence[str],
    *,
    pages: Sequence[int] | None = None,
) -> list[RedactionRect]:
    """
    Presets v1 engine (mono-line):
    - Extract words + bboxes
    - Group into lines
    - Rebuild each line as text
    - Apply preset regex to the line
    - Map match ranges back to word bboxes -> redaction rectangles

    Notes:
    - Phone preset: broad regex + phonenumbers validation (strong false-positive reduction).
    - Multi-line matching is not supported yet in v1.
    """
    if not pdf_bytes:
        raise ValueError("Empty PDF bytes.")
    if not presets:
        raise ValueError("At least one preset must be provided.")

    preset_defs = [_get_preset(p) for p in presets]
    compiled = [(re.compile(p.pattern, p.flags), p.post_filter) for p in preset_defs]

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        if pages is None:
            page_indexes = list(range(doc.page_count))
        else:
            page_indexes = list(pages)
            for i in page_indexes:
                if i < 0 or i >= doc.page_count:
                    raise ValueError(f"Invalid page index: {i}")

        out: list[RedactionRect] = []

        for page_idx in page_indexes:
            page = doc.load_page(page_idx)
            lines = _group_words_by_line(page)

            for line_words in lines:
                line_text, spans = _build_line_text_and_spans(line_words)

                for rx, post_filter in compiled:
                    for m in rx.finditer(line_text):
                        match_text = m.group(0)
                        if post_filter is not None and not post_filter(match_text):
                            continue

                        start, end = m.start(), m.end()
                        hit_spans = [s for s in spans if not (s.end <= start or s.start >= end)]
                        if not hit_spans:
                            continue

                        union = _rect_union(hit_spans)
                        out.append(
                            RedactionRect(
                                page=page_idx,
                                x0=float(union.x0),
                                y0=float(union.y0),
                                x1=float(union.x1),
                                y1=float(union.y1),
                            )
                        )

        return out
    finally:
        doc.close()
