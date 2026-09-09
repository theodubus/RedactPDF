"""Zones qu'aucune règle textuelle n'a pu lire.

Mesuré le 9 septembre 2026, avant que ce contrôle existe : sur un PDF scanné sans
couche texte, une règle « Dupont » et le preset téléphone rendaient tous deux
HTTP 200, image intacte, donnée lisible à l'oeil. C'est le mode d'échec que
l'accroche du projet déclare impossible, atteint sans le moindre message.
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from redactpdf.main import app

client = TestClient(app)


def _png(text: str, size: tuple[int, int] = (900, 200)) -> io.BytesIO:
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((20, 80), text, fill="black")
    buf = io.BytesIO()
    image.save(buf, "PNG")
    buf.seek(0)
    return buf


def _scan() -> bytes:
    """Un scan : le texte n'existe que dans l'image, la page n'a aucune couche texte."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    c.drawImage(ImageReader(_png("Nom : Jean Dupont   Tel : 06 12 34 56 78")),
                40, height - 260, width=500, height=110)
    c.showPage()
    c.save()
    return buf.getvalue()


def _hybrid() -> bytes:
    """Le cas qui a tué la première version du contrôle : texte en dur ET zone scannée.

    Tester « la page a-t-elle du texte » ne détecte rien ici. Le logo, lui, doit
    rester sous le seuil.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    c.setFont("Helvetica", 12)
    c.drawString(60, height - 70, "SOCIETE EXEMPLE SARL")
    c.drawString(60, height - 90, "Client : Marie Martin")
    c.drawImage(ImageReader(_png("Tableau scanne : Jean Dupont")),
                60, height - 320, width=460, height=92)
    c.drawImage(ImageReader(_png("logo", (60, 60))), 480, height - 70, width=40, height=40)
    c.showPage()
    c.save()
    return buf.getvalue()


def _post(pdf: bytes, payload: dict):
    return client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )


@pytest.mark.integration
def test_a_scan_no_longer_exports_silently() -> None:
    """Le trou d'origine. 409, pas 200."""
    resp = _post(_scan(), {"searches": [{"query": "Dupont"}]})

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["status"] == "inconclusive"
    assert detail["reason"] == "opaque_regions"
    assert len(detail["regions"]) == 1


@pytest.mark.integration
def test_only_the_scanned_block_is_reported_on_a_hybrid_page() -> None:
    """Le tableau scanné est signalé, le logo non : le seuil de taille les sépare."""
    resp = _post(_hybrid(), {"searches": [{"query": "Dupont"}]})

    assert resp.status_code == 409, resp.text
    regions = resp.json()["detail"]["regions"]
    assert len(regions) == 1
    assert regions[0]["page_share"] > 0.05


@pytest.mark.integration
def test_nothing_is_reported_without_a_textual_rule() -> None:
    """Sans règle textuelle, rien n'a été promis, donc rien n'est à signaler."""
    resp = _post(_scan(), {"rects": [{"page": 0, "x0": 50, "y0": 50, "x1": 100, "y1": 100}]})

    assert resp.status_code == 200, resp.text


@pytest.mark.integration
def test_ignore_mode_is_an_explicit_choice() -> None:
    """`ignore` rend le fichier : c'est un choix nommé, pas un repli silencieux."""
    resp = _post(
        _scan(),
        {"searches": [{"query": "Dupont"}], "options": {"image_regions": "ignore"}},
    )

    assert resp.status_code == 200, resp.text


@pytest.mark.integration
def test_review_mode_accepts_an_acknowledgement() -> None:
    """L'humain a regardé la zone : l'export part."""
    pdf = _scan()
    first = _post(pdf, {"searches": [{"query": "Dupont"}]})
    box = first.json()["detail"]["regions"][0]["bbox"]

    resp = _post(
        pdf,
        {"searches": [{"query": "Dupont"}], "acknowledged_regions": [{"page": 0, "bbox": box}]},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
def test_block_mode_ignores_acknowledgements() -> None:
    """`block` est le mode non interactif : un script ne clique pas.

    Seule une règle géométrique y déverrouille. Si l'acquittement suffisait,
    `block` ne serait qu'un `review` avec un autre nom.
    """
    pdf = _scan()
    first = _post(pdf, {"searches": [{"query": "Dupont"}]})
    box = first.json()["detail"]["regions"][0]["bbox"]

    resp = _post(
        pdf,
        {
            "searches": [{"query": "Dupont"}],
            "options": {"image_regions": "block"},
            "acknowledged_regions": [{"page": 0, "bbox": box}],
        },
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.integration
def test_a_geometric_rule_covering_the_region_unlocks_block_mode() -> None:
    """Dessiner dessus traite la zone, et l'éteint même en mode le plus strict."""
    pdf = _scan()
    first = _post(pdf, {"searches": [{"query": "Dupont"}]})
    x0, y0, x1, y1 = first.json()["detail"]["regions"][0]["bbox"]

    resp = _post(
        pdf,
        {
            "searches": [{"query": "Dupont"}],
            "options": {"image_regions": "block"},
            "rects": [{"page": 0, "x0": x0, "y0": y0, "x1": x1, "y1": y1}],
        },
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
def test_a_rectangle_that_does_not_quite_cover_still_reports() -> None:
    """Régression : le seuil par ratio de surface laissait passer une bande lisible.

    La première version acceptait une couverture de 95 % de la *surface*. Mesuré
    sur une zone de 320 x 120 pt, cela laissait dépasser une bande de 16 pt de
    large sur toute la hauteur, soit trois caractères en corps 9, sans un mot.
    La surface ignore la forme ; on exige donc un rectangle qui contienne la zone.
    """
    pdf = _scan()
    first = _post(pdf, {"searches": [{"query": "Dupont"}]})
    x0, y0, x1, y1 = first.json()["detail"]["regions"][0]["bbox"]

    resp = _post(
        pdf,
        {
            "searches": [{"query": "Dupont"}],
            "options": {"image_regions": "block"},
            # Il manque seize points sur la droite.
            "rects": [{"page": 0, "x0": x0, "y0": y0, "x1": x1 - 16, "y1": y1}],
        },
    )
    assert resp.status_code == 409, resp.text
