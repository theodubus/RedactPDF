"""Resserrement vertical des rectangles, sur la fixture qui l'exerce vraiment.

La boîte de ligne rendue par l'extracteur est plus haute que les glyphes qu'elle
contient. `_tighten_rect_vertical` la rabote pour qu'un rectangle ne déborde pas
sur la ligne du dessous. Tant que les lignes sont largement espacées, le débord
tombe dans du blanc et rien ne le révèle : sur les quatorze fixtures d'avant
celle-ci, jamais moins de 5 mm entre deux lignes, le resserrement était un
non-opérant intégral.

C'est pourtant ce mécanisme qui a produit le caviardage incomplet constaté sur
une fiche de paie réelle, document à interligne serré. D'où la fixture 015.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from redactpdf.main import app
from tests.utils_pdf import extract_text

client = TestClient(app)
FIXTURE = Path(__file__).parent / "fixtures" / "generated" / "015_tight_leading.pdf"


def _redact(query: str) -> str:
    resp = client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", FIXTURE.read_bytes(), "application/pdf"),
            "payload": (None, json.dumps({"searches": [{"query": query}]}), "application/json"),
        },
    )
    assert resp.status_code == 200, resp.text
    return extract_text(resp.content)


@pytest.mark.integration
def test_tight_leading_does_not_eat_the_line_below() -> None:
    """Bloc A, interligne 3,5 mm à 9 pt : la ligne suivante doit survivre entière.

    C'est la régression que le corpus ne couvrait pas. Sans le resserrement,
    `CONSERVER_A` disparaît avec la cible : mesuré, pas supposé.
    """
    out = _redact("SECRET_ABC123")

    assert "SECRET_ABC123" not in out
    assert "CONSERVER_A doit rester entier" in out
    assert "CONSERVER_B aussi" in out


@pytest.mark.integration
def test_tight_leading_leaves_the_other_block_alone() -> None:
    """Caviarder le bloc A ne doit rien coûter au bloc B, plus bas sur la page."""
    out = _redact("SECRET_ABC123")

    assert "CIBLE_SERREE" in out
    assert "FRAGILE_B est mange sous la limite" in out


@pytest.mark.integration
def test_below_the_breakdown_point_the_next_line_is_damaged() -> None:
    """Bloc B, interligne 2,5 mm : le resserrement ne suffit plus.

    Ce test **caractérise une limite connue, il ne la bénit pas.** Il existe pour
    que docs/SECURITY.md ne mente pas : si quelqu'un fait tenir le resserrement
    sous ce seuil, ce test échoue et la limite doit être retirée de la
    documentation dans le même changement.
    """
    out = _redact("CIBLE_SERREE")

    assert "CIBLE_SERREE" not in out
    # La ligne du dessous perd des mots : "est mange sous la" disparaît.
    assert "FRAGILE_B est mange sous la limite" not in out
    assert "FRAGILE_B" in out
    # Deux lignes plus bas, hors de portée, intacte.
    assert "FRAGILE_C ensuite" in out
