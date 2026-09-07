from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from redactpdf.audit import AuditOptions, audit_pdf_text

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


@pytest.mark.integration
def test_failed_export_explains_a_match_split_across_lines() -> None:
    """Le rapport d'échec doit dire *pourquoi*, pas seulement *quoi*.

    Sur un tableau « Nom | Prénom », les deux cellules partagent la même ligne
    de base : le moteur refuse volontairement de les apparier (c'est ce qui
    empêche les fusions inter-colonnes), tandis que l'audit lit un texte de page
    aplati où les deux se suivent. L'utilisateur reçoit un 400 légitime, mais
    rien ne l'oriente vers ce qui débloque tant que le rapport ne nomme pas la
    cause.
    """
    from io import BytesIO

    from fastapi.testclient import TestClient
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas

    from redactpdf.main import app

    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    c.setFont("Helvetica", 11)
    c.drawString(25 * mm, height - 50 * mm, "Dupont")
    c.drawString(80 * mm, height - 50 * mm, "Jean")
    c.showPage()
    c.save()

    payload = {
        "rects": [],
        "searches": [
            {
                "query": "Dupont Jean",
                "options": {"case_sensitive": False, "whole_word": True},
                "scope": {"pages": None},
            }
        ],
    }
    resp = TestClient(app).post(
        "/redact/apply",
        files={
            "file": ("in.pdf", buf.getvalue(), "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )

    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert "line_break_split" in body["diagnostics"]

    matches = body["components"]["searches"]["failed"][0]["report"]["matches"]
    assert any(m["spans_line_break"] for m in matches)
