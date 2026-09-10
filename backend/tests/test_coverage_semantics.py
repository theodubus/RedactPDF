"""`pass` ne doit pas vouloir dire trois choses différentes.

Le produit a trois issues conceptuellement distinctes, et jusqu'au 10 septembre
2026 elles rendaient un rapport **byte pour byte identique** :

    page de texte, tout vérifié          status=pass, mêmes clés, même en-tête
    scan, zone acquittée par l'humain    status=pass, mêmes clés, même en-tête
    scan, image_regions=ignore           status=pass, mêmes clés, même en-tête

Un appelant de l'API ne pouvait pas distinguer « la machine a tout lu » de
« personne n'a rien regardé ». `X-Redaction-Audit-Status: pass` est l'actif
principal du projet ; le laisser couvrir les trois cas le vide de son sens.

`status` n'a pas changé : l'audit a bien relu le texte de la sortie et n'y a rien
trouvé, ce qui reste vrai dans les trois cas. C'est un axe distinct qui manquait,
`coverage`, qui dit de quoi cette relecture était faite.
"""
from __future__ import annotations

import base64
import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from redactpdf.main import app

client = TestClient(app)
TARGET = "Dupont"


def _scan() -> bytes:
    """Une page entièrement scannée : aucune couche texte, rien de lisible."""
    source = pymupdf.open()
    page = source.new_page()
    page.insert_text((60, 120), f"Jean {TARGET}", fontname="helv", fontsize=28)
    pix = page.get_pixmap(dpi=120)
    source.close()

    doc = pymupdf.open()
    dest = doc.new_page()
    dest.insert_image(dest.rect, pixmap=pix)
    out = doc.tobytes()
    doc.close()
    return out


def _plain() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), f"Jean {TARGET}", fontname="helv", fontsize=12)
    out = doc.tobytes()
    doc.close()
    return out


def _apply(pdf: bytes, payload: dict[str, object]):
    return client.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )


def _report(resp) -> dict[str, object]:
    return json.loads(base64.b64decode(resp.headers["X-Redaction-Audit-Report-B64"]))


@pytest.mark.integration
def test_a_fully_read_document_is_complete() -> None:
    resp = _apply(_plain(), {"searches": [{"query": TARGET}]})

    assert resp.status_code == 200, resp.text
    assert resp.headers["X-Redaction-Coverage"] == "complete"
    coverage = _report(resp)["coverage"]
    assert coverage["level"] == "complete"
    assert coverage["checked"] is True
    assert coverage["unread_regions"] == 0
    assert "note" not in coverage


@pytest.mark.integration
def test_a_human_acknowledgement_is_not_a_machine_verification() -> None:
    pdf = _scan()
    refused = _apply(pdf, {"searches": [{"query": TARGET}]})
    assert refused.status_code == 409, refused.text[:200]

    acks = [
        {"page": z["page"], "bbox": z["bbox"]}
        for z in refused.json()["detail"]["opaque_regions"]
    ]
    resp = _apply(pdf, {"searches": [{"query": TARGET}], "acknowledged_regions": acks})

    assert resp.status_code == 200, resp.text[:200]
    assert resp.headers["X-Redaction-Coverage"] == "acknowledged"
    coverage = _report(resp)["coverage"]
    assert coverage["unread_regions"] == 1
    assert coverage["acknowledged_regions"] == 1
    assert "note" in coverage


@pytest.mark.integration
def test_an_explicit_opt_out_is_never_reported_as_complete() -> None:
    """Le pire des trois : l'appelant a renoncé au contrôle, le rapport disait « complete »."""
    resp = _apply(
        _scan(), {"searches": [{"query": TARGET}], "options": {"image_regions": "ignore"}}
    )

    assert resp.status_code == 200, resp.text[:200]
    assert resp.headers["X-Redaction-Coverage"] == "skipped"
    coverage = _report(resp)["coverage"]
    assert coverage["level"] == "skipped"
    assert coverage["checked"] is False
    assert "note" in coverage


@pytest.mark.integration
def test_a_geometric_rule_alone_is_complete() -> None:
    """Sans règle textuelle rien n'a été promis, donc rien n'a manqué.

    Un rectangle est exécuté, pas lu : il n'y a aucune lecture dont on pourrait
    dire qu'elle a échoué.
    """
    resp = _apply(_scan(), {"rects": [{"page": 0, "x0": 40, "y0": 40, "x1": 300, "y1": 200}]})

    assert resp.status_code == 200, resp.text[:200]
    assert resp.headers["X-Redaction-Coverage"] == "complete"


@pytest.mark.integration
def test_the_three_reports_are_not_interchangeable() -> None:
    """L'assertion qui aurait échoué avant : les trois rapports étaient identiques."""
    pdf = _scan()
    refused = _apply(pdf, {"searches": [{"query": TARGET}]})
    acks = [
        {"page": z["page"], "bbox": z["bbox"]}
        for z in refused.json()["detail"]["opaque_regions"]
    ]

    levels = {
        _apply(_plain(), {"searches": [{"query": TARGET}]}).headers["X-Redaction-Coverage"],
        _apply(pdf, {"searches": [{"query": TARGET}], "acknowledged_regions": acks}).headers[
            "X-Redaction-Coverage"
        ],
        _apply(
            pdf, {"searches": [{"query": TARGET}], "options": {"image_regions": "ignore"}}
        ).headers["X-Redaction-Coverage"],
    }

    assert levels == {"complete", "acknowledged", "skipped"}
