from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.audit import AuditOptions, audit_pdf_text

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "generated"
SECRET_FIXTURE = FIXTURES_DIR / "001_secret_text.pdf"
SECRET = "SECRET_ABC123"


@pytest.mark.unit
def test_audit_fails_when_secret_present_substring_case_sensitive() -> None:
    pdf_bytes = SECRET_FIXTURE.read_bytes()

    report = audit_pdf_text(
        pdf_bytes,
        AuditOptions(
            patterns=[SECRET],
            regex=False,
            case_sensitive=True,
        ),
    )

    assert report["status"] == "fail"
    assert report["total_matches"] >= 1
    assert SECRET in report["patterns"]
    assert report["matched_pages"], "Should report at least one matched page"
    assert any(
        (SECRET in m.get("match", "")) or (SECRET in m.get("snippet", ""))
        for m in report.get("matches", [])
    )


@pytest.mark.unit
def test_audit_passes_when_case_sensitive_pattern_does_not_match() -> None:
    pdf_bytes = SECRET_FIXTURE.read_bytes()

    # Minuscule : doit ne pas matcher en case-sensitive
    report = audit_pdf_text(
        pdf_bytes,
        AuditOptions(
            patterns=["secret_abc123"],
            regex=False,
            case_sensitive=True,
        ),
    )

    assert report["status"] == "pass"
    assert report["total_matches"] == 0
    assert report["matched_pages"] == []
    assert report["matches"] == []


@pytest.mark.unit
def test_audit_regex_finds_secret_when_regex_enabled() -> None:
    pdf_bytes = SECRET_FIXTURE.read_bytes()

    # Regex volontairement simple
    pattern = r"SECRET_[A-Z0-9]+"

    report = audit_pdf_text(
        pdf_bytes,
        AuditOptions(
            patterns=[pattern],
            regex=True,
            case_sensitive=True,
        ),
    )

    assert report["status"] == "fail"
    assert report["total_matches"] >= 1

    # Vérifie qu'au moins un match correspond à la regex
    assert any(
        re.fullmatch(pattern, m.get("match", "")) is not None
        for m in report.get("matches", [])
    ), "Audit should include a match that satisfies the regex"
