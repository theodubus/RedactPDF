"""L'audit relit la sortie avec deux moteurs, pas avec celui qui l'a écrite.

Relire avec PyMuPDF seul, la bibliothèque qui vient de caviarder, corrèle par
construction les angles morts du moteur et ceux du contrôle : ce qu'il n'a pas su
apparier, il ne saura pas le retrouver. `pypdf` lit en second, et une
correspondance trouvée par l'un des deux suffit à refuser l'export.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient

import redactpdf.audit as audit_module
from redactpdf.main import app

client = TestClient(app)
FIXTURES = Path(__file__).parent / "fixtures" / "generated"
SECRET = "SECRET_ABC123"


def _apply(pdf: bytes, payload: dict[str, Any]):
    return client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )


def _blind(_pdf_bytes: bytes) -> list[str]:
    """Un extracteur qui ne voit rien, pour vérifier que l'autre travaille."""
    return []


@pytest.mark.integration
def test_report_names_both_extractors() -> None:
    """Le rapport dit quels moteurs ont lu, pour que « pass » soit interprétable."""
    pdf = (FIXTURES / "001_secret_text.pdf").read_bytes()
    resp = _apply(pdf, {"rects": [], "audit": {"patterns": [SECRET]}})

    assert resp.status_code == 400, resp.text
    report = resp.json()["components"]["audit"]
    assert report["extractors"] == {"pymupdf": "ok", "pypdf": "ok"}


@pytest.mark.integration
def test_second_engine_catches_what_the_first_cannot_see(monkeypatch: pytest.MonkeyPatch) -> None:
    """Moteur principal aveugle : l'export doit rester refusé.

    C'est le test qui rend la conception non décorative. S'il passe encore quand
    on retire `pypdf`, c'est que le second moteur ne sert à rien.
    """
    monkeypatch.setattr(
        audit_module,
        "_EXTRACTORS",
        [("pymupdf", _blind), ("pypdf", audit_module._extract_pages_pypdf)],
    )
    pdf = (FIXTURES / "001_secret_text.pdf").read_bytes()
    resp = _apply(pdf, {"rects": [], "audit": {"patterns": [SECRET]}})

    assert resp.status_code == 400, resp.text
    report = resp.json()["components"]["audit"]
    assert report["total_matches"] >= 1
    assert all(m["seen_by"] == ["pypdf"] for m in report["matches"])


@pytest.mark.integration
def test_a_broken_extractor_is_recorded_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un moteur en panne réduit la couverture : le rapport doit le dire.

    Sans cette trace, un « pass » obtenu avec un seul lecteur serait
    indiscernable d'un « pass » obtenu avec deux.
    """

    def _explodes(_pdf_bytes: bytes) -> list[str]:
        raise RuntimeError("moteur indisponible")

    monkeypatch.setattr(
        audit_module,
        "_EXTRACTORS",
        [("pymupdf", audit_module._extract_pages_pymupdf), ("pypdf", _explodes)],
    )
    pdf = (FIXTURES / "001_secret_text.pdf").read_bytes()
    resp = _apply(pdf, {"rects": [], "audit": {"patterns": [SECRET]}})

    assert resp.status_code == 400, resp.text
    report = resp.json()["components"]["audit"]
    assert report["extractors"]["pymupdf"] == "ok"
    assert report["extractors"]["pypdf"].startswith("failed: RuntimeError")


@pytest.mark.integration
def test_agreement_is_reported_on_a_successful_export() -> None:
    """Un export réussi porte aussi la trace des deux lecteurs, en en-tête."""
    pdf = (FIXTURES / "001_secret_text.pdf").read_bytes()
    resp = _apply(pdf, {"searches": [{"query": SECRET}]})

    assert resp.status_code == 200, resp.text
    raw = resp.headers["X-Redaction-Audit-Report-B64"]
    report = json.loads(base64.urlsafe_b64decode(raw))

    # C'est sur un succès que l'information compte : « pass » validé par deux
    # lecteurs ne vaut pas « pass » validé par un seul, l'autre étant en panne.
    assert report["extractors"] == {"pymupdf": "ok", "pypdf": "ok"}
    assert SECRET not in pymupdf.open(stream=resp.content).load_page(0).get_text()
