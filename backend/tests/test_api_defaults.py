"""Les défauts de payload de l'API, figés par le comportement observable.

Ces défauts ne servent qu'aux appelants directs de l'API : l'interface envoie
toujours ses propres valeurs. C'est précisément ce qui les rend faciles à faire
dériver sans que personne ne s'en aperçoive, et l'audit ne peut pas rattraper la
dérive puisqu'il rejoue la même option.

La règle est celle de A0 : un défaut qui caviarde moins est un défaut qui fuit.
Chaque test ci-dessous échoue si un défaut bascule du côté qui retire moins.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from redactpdf.main import app
from tests.utils_pdf import extract_text

client = TestClient(app)
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "generated"


def _apply(fixture: str, payload: dict) -> str:
    pdf_in = (FIXTURES_DIR / fixture).read_bytes()
    resp = client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf_in, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )
    assert resp.status_code == 200, resp.text
    return extract_text(resp.content)


@pytest.mark.integration
def test_search_without_options_folds_accents() -> None:
    """« Leo » sans options doit aussi retirer « Léo ».

    Le repliage d'accents est un sur-ensemble strict. Le défaut inverse
    produisait un export en 200 avec la variante accentuée intacte et aucun
    signal, l'audit rejouant le même réglage.
    """
    out = _apply("012_ignore_accents.pdf", {"searches": [{"query": "Leo"}]})
    assert "Leo" not in out
    assert "Léo" not in out


@pytest.mark.integration
def test_regex_without_options_folds_accents() -> None:
    """Même exigence pour une règle regex sans options."""
    out = _apply("012_ignore_accents.pdf", {"regexes": [{"patterns": ["Leo"]}]})
    assert "Leo" not in out
    assert "Léo" not in out


@pytest.mark.integration
def test_search_without_options_matches_inside_words() -> None:
    """« CAT » sans options doit aussi mordre dans « CATCH ».

    Garde-fou contre un alignement mal orienté sur l'interface : côté UI,
    « Sous-mot » est désactivé par défaut, ce qui vaut `whole_word: true`. Le
    reprendre ici ferait caviarder *moins*. `whole_word` reste donc à False.
    """
    out = _apply("007_whole_word_cat_catch.pdf", {"searches": [{"query": "CAT"}]})
    assert "CAT" not in out
    assert "CATCH" not in out
    # Le reste de la ligne survit : c'est bien un retrait glyphe à glyphe.
    assert "CH" in out


@pytest.mark.integration
def test_image_options_default_to_pixel_redaction() -> None:
    """Rappel de A0, dans le même fichier que les autres défauts de payload.

    Un payload sans `options` doit caviarder les pixels, pas dessiner un calque
    noir sur une image intacte.
    """
    from redactpdf.main import OptionsModel

    opts = OptionsModel()
    assert opts.image_mode == "pixels"
    assert opts.apply_graphics is True
    assert opts.sanitize_metadata is True
    assert opts.remove_annotations is True
    assert opts.remove_attachments is True
