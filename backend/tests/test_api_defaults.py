"""Les défauts de payload de l'API, figés par le comportement observable.

Ces défauts ne servent qu'aux appelants directs de l'API : l'interface envoie
toujours ses propres valeurs. C'est précisément ce qui les rend faciles à faire
dériver sans que personne ne s'en aperçoive, et l'audit ne peut pas rattraper la
dérive puisqu'il rejoue la même option.

La règle n'est pas « caviarder le plus possible » mais « faire ce que la règle
voulait dire », et les deux ne coïncident pas toujours. Retirer « Léo » pour une
règle « Leo » est ce qui était visé ; retirer « Dupontel » pour une règle
« Dupont » est mutiler un tiers. Là où l'intention est vraiment ambiguë, on
retient l'option qui retire le plus.
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
def test_search_without_options_matches_whole_words_only() -> None:
    """« CAT » sans options ne doit pas mordre dans « CATCH ».

    Deux mots différents. Apparier le second reviendrait à caviarder un terme que
    personne n'a visé : une règle « Dupont » emportait « Dupontel », le nom de
    quelqu'un d'autre.
    """
    out = _apply("007_whole_word_cat_catch.pdf", {"searches": [{"query": "CAT"}]})
    assert "CATCH" in out
    # Le jeton isolé, lui, est bien parti.
    assert "Standalone token: CAT" not in out


@pytest.mark.integration
def test_whole_word_default_still_crosses_punctuation() -> None:
    """Ce qui rend le défaut mot-entier tenable : la ponctuation reste une frontière.

    C'est la condition qui empêche `whole_word=True` de manquer les données que
    cet outil vise. Sans elle, « Dupont » ne serait plus trouvé dans une adresse
    e-mail ni dans un nom composé, et le défaut deviendrait une fuite.
    """
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    c.setFont("Helvetica", 11)
    for i, line in enumerate(
        ["Mail : jean.dupont@example.com", "Compose : Dupont-Martin", "Elision : l'affaire Dupont"]
    ):
        c.drawString(60, height - 90 - i * 22, line)
    c.showPage()
    c.save()

    resp = client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", buf.getvalue(), "application/pdf"),
            "payload": (None, json.dumps({"searches": [{"query": "Dupont"}]}), "application/json"),
        },
    )
    assert resp.status_code == 200, resp.text
    out = extract_text(resp.content).lower()
    assert "dupont" not in out


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
