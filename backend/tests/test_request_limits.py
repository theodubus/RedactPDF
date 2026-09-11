"""Plafond sur le nombre de rectangles d'une requête.

Chaque rectangle est une annotation de caviardage posée puis appliquée par
PyMuPDF ; le coût est linéaire mais le facteur n'est pas petit. Mesuré sur une
page A4, avec le reste du pipeline (plan, application, audit deux moteurs) :

    499 rectangles   HTTP 200 en 1,5 s
    501 rectangles   HTTP 400 immédiat
    5000 rectangles  HTTP 400 immédiat

Le plafond est vérifié *avant* d'ouvrir le document, donc un payload absurde
coûte le temps de la validation Pydantic et rien de plus. 500 est très au-delà
de ce qu'une main dessine : la limite protège le processus d'un payload
fabriqué, elle ne contraint aucun usage réel.

Le compte porte sur `rects` + `full_page_rects` ensemble : compter les deux
séparément laisserait passer le double par la porte d'à côté.
"""
from __future__ import annotations

import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from redactpdf.main import MAX_RECTS_PER_REQUEST, app

client = TestClient(app)


def _page() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Jean Dupont", fontname="helv", fontsize=12)
    out = doc.tobytes()
    doc.close()
    return out


def _rects(n: int) -> list[dict[str, float | int]]:
    """Des rectangles minuscules, disjoints, sur la seule page du document."""
    return [
        {
            "page": 0,
            "x0": 20 + (i % 50) * 10,
            "y0": 300 + (i // 50) * 4,
            "x1": 24 + (i % 50) * 10,
            "y1": 303 + (i // 50) * 4,
        }
        for i in range(n)
    ]


def _post(payload: dict[str, object]):
    return client.post(
        "/redact/apply",
        files={"file": ("input.pdf", _page(), "application/pdf")},
        data={"payload": json.dumps(payload)},
    )


@pytest.mark.integration
def test_the_cap_is_not_reached_by_a_realistic_payload() -> None:
    resp = _post({"rects": _rects(MAX_RECTS_PER_REQUEST - 1)})

    assert resp.status_code == 200, resp.text


@pytest.mark.integration
def test_one_rectangle_too_many_is_refused() -> None:
    resp = _post({"rects": _rects(MAX_RECTS_PER_REQUEST + 1)})

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["status"] == "too_many_rects"
    assert detail["count"] == MAX_RECTS_PER_REQUEST + 1
    assert detail["limit"] == MAX_RECTS_PER_REQUEST


@pytest.mark.integration
def test_the_two_lists_are_counted_together() -> None:
    """Sinon le plafond se contourne en répartissant sur les deux champs."""
    half = MAX_RECTS_PER_REQUEST // 2 + 1
    resp = _post({"rects": _rects(half), "full_page_rects": _rects(half)})

    assert resp.status_code == 400
    assert resp.json()["detail"]["count"] == 2 * half
