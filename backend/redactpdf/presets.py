from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import phonenumbers

from redactpdf.multiline_regex_engine import iter_regex_hits
from redactpdf.redaction import RedactionRect


# For numbers without a leading '+' we need a region hint.
# Default to FR but allow overriding through env var.
def _default_region() -> str:
    return os.getenv("REDACT_DEFAULT_REGION", "FR").upper()


DEFAULT_REGION = _default_region()


@dataclass(frozen=True)
class PresetDefinition:
    key: str
    label: str
    description: str
    pattern: str
    post_filter: Callable[[str], bool] | None = None
    multiline: bool = False


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
    - Multi-line matching is supported (v2) but still relies on text extractability.
    """
    normalized = _normalize_phone_candidate(match_text)

    digits_only = normalized[1:] if normalized.startswith("+") else normalized
    if not digits_only.isdigit():
        return False
    if len(digits_only) < 7 or len(digits_only) > 15:
        return False

    try:
        if normalized.startswith("+"):
            num = phonenumbers.parse(normalized, None)
        else:
            num = phonenumbers.parse(normalized, DEFAULT_REGION)

        if not phonenumbers.is_possible_number(num):
            return False
        if not phonenumbers.is_valid_number(num):
            return False
        return True
    except phonenumbers.NumberParseException:
        return False


# Presets:
# - email & credit_card remain mono-line (less risk of false positives).
# - phone uses multiline by default to handle the "06 12 34 / 56 78" case.
_PRESETS: dict[str, PresetDefinition] = {
    "email": PresetDefinition(
        key="email",
        label="Email",
        description=(
            "Matches common email addresses. Limitations: may miss exotic cases; "
            "relies on text being extractable (OCR not handled)."
        ),
        pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        post_filter=None,
        multiline=False,
    ),
    "phone": PresetDefinition(
        key="phone",
        label="Phone (international, validated)",
        description=(
            "Heuristically extracts phone-like candidates (international/national forms, "
            "common separators) and validates them using libphonenumber (phonenumbers). "
            "Multi-line matching is enabled by default to catch numbers split across lines. "
            "Numbers without '+' require a default region "
            f"(current DEFAULT_REGION={DEFAULT_REGION}). OCR not handled."
        ),
        pattern=r"\b(?:\+|00)?\s*(?:\d[\s().\-]?){6,20}\d\b",
        post_filter=_phone_post_filter,
        multiline=True,
    ),
    "credit_card": PresetDefinition(
        key="credit_card",
        label="Credit card (Luhn-filtered)",
        description=(
            "Matches 13..19-digit sequences with spaces/hyphens and validates with Luhn. "
            "Limitations: may still match some non-card identifiers; mono-line only."
        ),
        pattern=r"\b(?:\d[ -]*?){13,19}\b",
        post_filter=_credit_card_post_filter,
        multiline=False,
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


def _dedupe_rects(rects: list[RedactionRect]) -> list[RedactionRect]:
    seen: set[tuple[int, float, float, float, float]] = set()
    out: list[RedactionRect] = []
    for r in rects:
        k = (r.page, round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2))
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def find_redaction_rectangles_for_presets(
    pdf_bytes: bytes,
    presets: Sequence[str],
    *,
    pages: Sequence[int] | None = None,
) -> list[RedactionRect]:
    """
    Presets engine (regex -> rectangles) with optional post-filters.

    - Uses the unified regex engine that supports single-line and (optionally) multi-line
      matching across adjacent lines.
    - Presets are intentionally case-insensitive.
    - Post-filters reduce false positives:
        - phone: validated with phonenumbers
        - credit_card: validated with Luhn

    Notes:
    - Multi-line is enabled only for presets that opt into it (phone by default).
    - For multi-line matches, the engine may return multiple rectangles (one per involved line).
    """
    if not pdf_bytes:
        raise ValueError("Empty PDF bytes.")
    if not presets:
        raise ValueError("At least one preset must be provided.")

    preset_defs = [_get_preset(p) for p in presets]
    out: list[RedactionRect] = []

    for pdef in preset_defs:
        # Presets are intentionally case-insensitive for usability and consistency.
        hits = iter_regex_hits(
            pdf_bytes,
            [pdef.pattern],
            case_sensitive=False,
            pages=pages,
            multiline=pdef.multiline,
        )

        if pdef.post_filter is None:
            for h in hits:
                out.extend(list(h.rects))
            continue

        for h in hits:
            if pdef.post_filter(h.match):
                out.extend(list(h.rects))

    return _dedupe_rects(out)
