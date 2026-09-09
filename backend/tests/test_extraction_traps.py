"""Formes de texte que l'extracteur rend autrement qu'à l'écran.

Chacune vient d'un piège construit et mesuré, pas d'une relecture de code. Le
banc complet, y compris les formes qui passaient déjà, est décrit dans
docs/SECURITY.md.
"""
from __future__ import annotations

import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from redactpdf.main import app

client = TestClient(app)


def _post(pdf: bytes, payload: dict):
    payload.setdefault("options", {})["image_regions"] = "ignore"
    return client.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )


def _text(pdf: bytes) -> str:
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def _letterspaced(word: str, size: float = 18, extra: float = 3.5) -> bytes:
    """Un mot interlettré, comme sur un papier à lettres.

    Au-delà d'environ 18 % du corps en interlettrage, mesuré sur Helvetica,
    l'extracteur coupe le mot lettre par lettre : l'écart entre glyphes y dépasse
    la largeur d'une espace. En dessous il reste entier, ce qui explique que le
    cas ne se voie que sur des titres et des en-têtes.
    """
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 80), "Cabinet juridique", fontsize=11)
    writer = pymupdf.TextWriter(page.rect)
    x = 72.0
    for ch in word:
        writer.append((x, 120), ch, fontsize=size)
        x += pymupdf.get_text_length(ch, fontname="helv", fontsize=size) + extra
    writer.write_text(page)
    out = doc.tobytes()
    doc.close()
    return out


@pytest.mark.integration
def test_a_letterspaced_name_is_found() -> None:
    """Régression : « BOURDILLON » s'extrayait « B O U R D I L L O N ».

    La règle ne trouvait rien, l'audit rejouait la même règle et ne trouvait rien
    non plus : HTTP 200 avec le nom parfaitement lisible en tête de page.

    L'écart ne suffit pas à trancher, il fait bien la largeur d'une espace à ce
    réglage. C'est la **forme du groupe** qui parle : une suite de mots d'une
    seule lettre à écarts réguliers.
    """
    pdf = _letterspaced("BOURDILLON")
    assert "B O U R D I L L O N" in _text(pdf), "le piège doit vraiment être coupé"

    resp = _post(pdf, {"searches": [{"query": "BOURDILLON"}]})

    assert resp.status_code == 200, resp.text[:200]
    assert int(resp.headers["X-Redaction-Search-Occurrences"]) == 1
    assert "BOURDILLON" not in "".join(_text(resp.content).split())


@pytest.mark.integration
def test_a_run_of_short_words_is_not_glued() -> None:
    """Le recollage ne doit pas souder de vrais mots courts.

    « il y a » n'aligne que deux mots d'une lettre, d'où le minimum de trois.
    Sans ce garde-fou, une requête pourrait traverser des mots sans rapport et
    caviarder au hasard.
    """
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 120), "il y a de la place", fontsize=14)
    pdf = doc.tobytes()
    doc.close()

    resp = _post(pdf, {"searches": [{"query": "yade", "options": {"whole_word": False}}]})

    assert resp.status_code == 200
    assert resp.headers["X-Redaction-Search-Occurrences"] == "0"
    assert "il y a de la place" in _text(resp.content)


def _encrypted(password: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 120), "Dossier de Bourdillon", fontsize=14)
    out = doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password
    )
    doc.close()
    return out


@pytest.mark.integration
def test_an_encrypted_document_says_what_is_missing() -> None:
    """Le refus portait le message brut de PyMuPDF, qui n'apprend rien.

    « document closed or encrypted » n'indique ni la cause ni le remède. Le refus
    porte maintenant un code que l'interface sait traduire.
    """
    resp = _post(_encrypted("secret"), {"searches": [{"query": "Bourdillon"}]})

    assert resp.status_code == 400
    assert resp.json()["detail"] == {"status": "encrypted", "reason": "password_required"}


@pytest.mark.integration
def test_a_wrong_password_is_distinguished_from_a_missing_one() -> None:
    """Redemander un mot de passe déjà fourni sans dire qu'il est faux est cruel."""
    resp = _post(
        _encrypted("secret"), {"searches": [{"query": "Bourdillon"}], "password": "faux"}
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["reason"] == "password_incorrect"


@pytest.mark.integration
def test_the_right_password_redacts_normally() -> None:
    """Déchiffré une fois à l'entrée, tout l'aval voit un PDF ordinaire."""
    resp = _post(
        _encrypted("secret"), {"searches": [{"query": "Bourdillon"}], "password": "secret"}
    )

    assert resp.status_code == 200, resp.text[:200]
    assert b"Bourdillon" not in resp.content


@pytest.mark.integration
def test_an_owner_password_alone_does_not_block_anything() -> None:
    """Le cas courant du PDF « protégé » : il s'ouvre sans rien demander."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 120), "Dossier de Bourdillon", fontsize=14)
    pdf = doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="secret",
        permissions=pymupdf.PDF_PERM_PRINT,
    )
    doc.close()

    resp = _post(pdf, {"searches": [{"query": "Bourdillon"}]})

    assert resp.status_code == 200, resp.text[:200]
    assert b"Bourdillon" not in resp.content
