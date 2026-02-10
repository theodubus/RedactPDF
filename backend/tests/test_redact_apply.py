from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.utils_pdf import extract_text

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "generated"


@pytest.mark.integration
def test_redact_apply_combines_search_and_presets_email() -> None:
    """
    Long-term regression test:
    - /redact/apply computes rectangles from the ORIGINAL PDF for search + presets,
      so email redaction cannot be broken by a prior partial search redaction.
    """
    pdf_path = FIXTURES_DIR / "011_apply_search_and_email.pdf"
    pdf_bytes = pdf_path.read_bytes()

    original_text = extract_text(pdf_bytes)
    assert "DUPONT" in original_text
    assert "alice.dupont@example.com" in original_text

    payload = {
        "rects": [],
        "search": {
            "query": "DUPONT",
            "options": {"case_sensitive": False, "whole_word": True, "ignore_accents": False},
            "scope": {"pages": None},
        },
        "presets": {
            "presets": ["email"],
            "scope": {"pages": None},
        },
        "options": {},
        # audit additionnel (optionnel) : on bannit le nom en sortie
        "audit": {"patterns": ["DUPONT"], "regex": False, "case_sensitive": False},
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"
    assert resp.headers.get("X-Redaction-Audit-Matches") == "0"

    redacted_text = extract_text(resp.content)

    # Email must be fully removed (no partial leftovers)
    assert "alice.dupont@example.com" not in redacted_text
    assert "dupont" not in redacted_text.casefold()

    # Ensure other content remains
    assert "Texte non sensible" in redacted_text

    # Optional: ensure no remaining whole-word name token
    assert re.search(r"(?i)\bdupont\b", redacted_text) is None


@pytest.mark.integration
def test_redact_apply_multiple_searches_and_presets() -> None:
    pdf_path = FIXTURES_DIR / "011_apply_search_and_email.pdf"
    pdf_bytes = pdf_path.read_bytes()

    original_text = extract_text(pdf_bytes)
    assert "DUPONT" in original_text
    assert "alice.dupont@example.com" in original_text
    assert "Texte non sensible" in original_text

    payload = {
        "rects": [],
        "searches": [
            {
                "query": "DUPONT",
                "options": {"case_sensitive": False, "whole_word": True, "ignore_accents": False},
                "scope": {"pages": None},
            },
            {
                "query": "Texte non sensible",
                "options": {"case_sensitive": False, "whole_word": False, "ignore_accents": False},
                "scope": {"pages": None},
            },
        ],
        "presets": {"presets": ["email"], "scope": {"pages": None}},
        "options": {},
        "audit": None,
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"
    assert resp.headers.get("X-Redaction-Audit-Matches") == "0"

    # Occurrences headers should exist
    assert resp.headers.get("X-Redaction-Search-Occurrences") is not None
    assert resp.headers.get("X-Redaction-Presets-Occurrences") is not None

    redacted_text = extract_text(resp.content)

    assert re.search(r"(?i)\bdupont\b", redacted_text) is None
    assert "Texte non sensible" not in redacted_text
    assert "alice.dupont@example.com" not in redacted_text

    # Not fully blank
    assert redacted_text.strip() != ""


@pytest.mark.integration
def test_redact_apply_multiple_regexes_email_and_phone() -> None:
    pdf_path = FIXTURES_DIR / "002_email_phone_one_line.pdf"
    pdf_bytes = pdf_path.read_bytes()

    original_text = extract_text(pdf_bytes)
    assert original_text.strip() != ""

    email_pat = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    phone_pat = r"(?:\+?\d[\d .()\-\s]{6,}\d)"

    assert re.search(email_pat, original_text) is not None
    assert re.search(phone_pat, original_text) is not None

    payload = {
        "rects": [],
        "regexes": [
            {
                "patterns": [email_pat],
                "case_sensitive": False,
                "multiline": False,
                "scope": {"pages": None},
            },
            {
                "patterns": [phone_pat],
                "case_sensitive": False,
                "multiline": False,
                "scope": {"pages": None},
            },
        ],
        "options": {},
        "audit": None,
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"

    redacted_text = extract_text(resp.content)

    assert re.search(email_pat, redacted_text, flags=re.IGNORECASE) is None
    assert re.search(phone_pat, redacted_text, flags=re.IGNORECASE) is None


@pytest.mark.integration
def test_redact_apply_multiline_regex_rule() -> None:
    pdf_path = FIXTURES_DIR / "003_phone_two_lines.pdf"
    pdf_bytes = pdf_path.read_bytes()

    original_text = extract_text(pdf_bytes)
    assert original_text.strip() != ""

    phone_pat = r"(?:\+?\d[\d\s().\-]{6,}\d)"
    assert re.search(phone_pat, original_text) is not None

    payload = {
        "rects": [],
        "regexes": [
            {
                "patterns": [phone_pat],
                "case_sensitive": False,
                "multiline": True,
                "scope": {"pages": None},
            }
        ],
        "options": {},
        "audit": None,
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"

    redacted_text = extract_text(resp.content)
    assert re.search(phone_pat, redacted_text, flags=re.IGNORECASE) is None


@pytest.mark.integration
def test_redact_apply_invalid_regex_in_regexes_returns_400() -> None:
    pdf_path = FIXTURES_DIR / "001_secret_text.pdf"
    pdf_bytes = pdf_path.read_bytes()

    payload = {
        "rects": [],
        "regexes": [
            {
                "patterns": ["([A-"],
                "case_sensitive": False,
                "multiline": False,
                "scope": {"pages": None},
            }
        ],
        "options": {},
        "audit": None,
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 400


@pytest.mark.integration
def test_redact_apply_search_ignore_accents_removes_leo_and_leo_accented() -> None:
    pdf_path = FIXTURES_DIR / "012_ignore_accents.pdf"
    pdf_bytes = pdf_path.read_bytes()
    original_text = extract_text(pdf_bytes)
    assert "Léo" in original_text or "LÉO" in original_text or "léo" in original_text.lower()
    assert "Leo" in original_text

    payload = {
        "rects": [],
        "searches": [
            {
                "query": "leo",
                "options": {
                    "case_sensitive": False,
                    "whole_word": True,
                    "ignore_accents": True,
                },
                "scope": {"pages": None},
            }
        ],
        "options": {},
        "audit": None,
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("accents.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"

    redacted_text = extract_text(resp.content)
    # On tolère la casse, on contrôle l'absence des deux variantes
    assert "leo" not in redacted_text.casefold()
    assert "léo" not in redacted_text.casefold()
    assert "Autre: rien" in redacted_text


@pytest.mark.integration
def test_redact_apply_regex_partial_redaction_substring_inside_word() -> None:
    """
    Objectif: si le pattern matche un sous-mot (ex CAT dans CATCH),
    on ne doit pas supprimer tout le mot mais uniquement la partie matchée.
    """
    pdf_path = FIXTURES_DIR / "007_whole_word_cat_catch.pdf"
    pdf_bytes = pdf_path.read_bytes()

    original_text = extract_text(pdf_bytes)
    assert "CAT" in original_text
    assert "CATCH" in original_text

    payload = {
        "rects": [],
        "regexes": [
            {
                "patterns": ["CAT"],  # pas de boundaries => match dans CATCH
                "case_sensitive": True,
                "multiline": False,
                "scope": {"pages": None},
            }
        ],
        "options": {},
        "audit": None,
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("cat.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"

    redacted_text = extract_text(resp.content)

    # "CAT" (token seul) supprimé
    assert re.search(r"(?<!\w)CAT(?!\w)", redacted_text) is None

    # "CATCH" ne doit plus exister en entier
    assert "CATCH" not in redacted_text

    # On s'attend à ce que la fin ("CH") reste (redaction partielle)
    assert re.search(r"(?<!\w)CH(?!\w)", redacted_text) is not None


@pytest.mark.integration
def test_redact_apply_regex_boundaries_keep_catch_intact() -> None:
    """
    Si l'UI désactive 'Sous-mot' pour une regex, le frontend peut entourer le pattern
    avec des frontières type (?<!\\w) ... (?!\\w).
    Ici on vérifie que CATCH reste inchangé.
    """
    pdf_path = FIXTURES_DIR / "007_whole_word_cat_catch.pdf"
    pdf_bytes = pdf_path.read_bytes()

    original_text = extract_text(pdf_bytes)
    assert "CAT" in original_text
    assert "CATCH" in original_text

    boundary_pat = r"(?<!\w)CAT(?!\w)"

    payload = {
        "rects": [],
        "regexes": [
            {
                "patterns": [boundary_pat],
                "case_sensitive": True,
                "multiline": False,
                "scope": {"pages": None},
            }
        ],
        "options": {},
        "audit": None,
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("cat.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"

    redacted_text = extract_text(resp.content)

    # Le token "CAT" seul doit être supprimé
    assert re.search(r"(?<!\w)CAT(?!\w)", redacted_text) is None

    # "CATCH" doit rester présent
    assert "CATCH" in redacted_text


@pytest.mark.integration
def test_redact_apply_regex_ignore_accents_pattern_ascii_matches_accented_and_plain() -> None:
    pdf_path = FIXTURES_DIR / "012_ignore_accents.pdf"
    pdf_bytes = pdf_path.read_bytes()

    original_text = extract_text(pdf_bytes)
    assert "Leo" in original_text
    assert "Léo" in original_text or "LÉO" in original_text or "léo" in original_text.lower()

    payload = {
        "rects": [],
        "searches": [],
        "regexes": [
            {
                "patterns": ["leo"],
                "case_sensitive": False,
                "multiline": False,
                "ignore_accents": True,
                "scope": {"pages": None},
            }
        ],
        "presets": None,
        "options": {},
        "audit": None,
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("accents.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"

    redacted_text = extract_text(resp.content)
    assert "leo" not in redacted_text.casefold()
    assert "léo" not in redacted_text.casefold()

    # garde-fou: du texte non sensible doit rester
    assert "rien" in redacted_text


@pytest.mark.integration
def test_redact_apply_regex_ignore_accents_pattern_accented_matches_plain_and_accented() -> None:
    pdf_path = FIXTURES_DIR / "012_ignore_accents.pdf"
    pdf_bytes = pdf_path.read_bytes()

    original_text = extract_text(pdf_bytes)
    assert "Leo" in original_text
    assert "Léo" in original_text or "LÉO" in original_text or "léo" in original_text.lower()

    payload = {
        "rects": [],
        "searches": [],
        "regexes": [
            {
                "patterns": ["léo"],
                "case_sensitive": False,
                "multiline": False,
                "ignore_accents": True,
                "scope": {"pages": None},
            }
        ],
        "presets": None,
        "options": {},
        "audit": None,
    }

    client = TestClient(app)
    resp = client.post(
        "/redact/apply",
        files={"file": ("accents.pdf", pdf_bytes, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Redaction-Audit-Status") == "pass"

    redacted_text = extract_text(resp.content)
    assert "leo" not in redacted_text.casefold()
    assert "léo" not in redacted_text.casefold()
    assert "rien" in redacted_text
