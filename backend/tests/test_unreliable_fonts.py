"""Polices dont l'extraction ne rend pas d'Unicode exploitable.

Mesuré avant d'écrire le détecteur, sur la même police TrueType intégrée en
`/Identity-H` :

    avec /ToUnicode   'Jean Dupont 06 12 34 56 78'
    sans /ToUnicode   'ðĊĆēÆêĚĕĔēęÆÖÜÆ×ØÆÙÚÆÛÜÆÝÞ'

La règle ne trouve rien, l'audit non plus puisqu'il lit le même texte, et
l'export partait en 200 avec la donnée parfaitement visible à l'écran.

Le critère n'est pas « police composite sans /ToUnicode ». Une première version
l'a cru et se serait déclenchée sur tout document CJK : les polices intégrées de
PyMuPDF utilisent `/UniGB-UTF16-H`, une CMap de registre qui donne l'Unicode à
elle seule. C'est `/Identity-H`, où le code est l'indice de glyphe dans la
police, qui rend `/ToUnicode` indispensable.
"""
from __future__ import annotations

import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from redactpdf.main import app
from redactpdf.opaque import find_unreliable_fonts

client = TestClient(app)


def _document(*, identity: bool, tounicode: bool) -> bytes:
    """Construit un dictionnaire de police à la main, sans dépendre d'une police système.

    Le détecteur ne lit que le dictionnaire ; la casse de l'extraction, elle, est
    établie par la mesure rapportée dans le docstring du module.
    """
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Jean Dupont", fontname="helv", fontsize=12)

    descendant = doc.get_new_xref()
    doc.update_object(
        descendant,
        "<< /Type /Font /Subtype /CIDFontType2 /BaseFont /Faux /CIDSystemInfo "
        "<< /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> >>",
    )
    entries = [
        "/Type /Font",
        "/Subtype /Type0",
        "/BaseFont /Faux",
        f"/Encoding /{'Identity-H' if identity else 'UniGB-UTF16-H'}",
        f"/DescendantFonts [ {descendant} 0 R ]",
    ]
    if tounicode:
        cmap = doc.get_new_xref()
        doc.update_object(cmap, "<< >>")
        doc.update_stream(cmap, b"/CIDInit /ProcSet findresource begin end")
        entries.append(f"/ToUnicode {cmap} 0 R")

    font = doc.get_new_xref()
    doc.update_object(font, "<< " + " ".join(entries) + " >>")

    # Référencer la police depuis les ressources de la page, sinon get_fonts l'ignore.
    # /Resources est une référence indirecte, donc on ne peut pas y écrire une clé
    # imbriquée depuis la page : il faut résoudre le xref et écrire dessus.
    _, resources_ref = doc.xref_get_key(page.xref, "Resources")
    doc.xref_set_key(int(str(resources_ref).split()[0]), "Font/FFaux", f"{font} 0 R")

    out = doc.tobytes()
    doc.close()
    return out


@pytest.mark.unit
def test_identity_encoding_without_tounicode_is_flagged() -> None:
    fonts = find_unreliable_fonts(_document(identity=True, tounicode=False))

    assert [f.subtype for f in fonts] == ["Type0"]
    assert fonts[0].page == 0


@pytest.mark.unit
def test_identity_encoding_with_tounicode_is_fine() -> None:
    assert find_unreliable_fonts(_document(identity=True, tounicode=True)) == []


@pytest.mark.unit
def test_a_registry_cmap_needs_no_tounicode() -> None:
    """Le faux positif qu'aurait produit la première version, sur tout document CJK."""
    assert find_unreliable_fonts(_document(identity=False, tounicode=False)) == []


@pytest.mark.unit
def test_a_simple_font_is_never_flagged() -> None:
    """Helvetica n'a pas de /ToUnicode et s'extrait parfaitement."""
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Jean Dupont", fontname="helv", fontsize=12)
    raw = doc.tobytes()
    doc.close()

    assert find_unreliable_fonts(raw) == []


@pytest.mark.integration
def test_an_unreadable_font_refuses_the_export() -> None:
    """Bout en bout : la page part en 409 au lieu de rendre un fichier."""
    pdf = _document(identity=True, tounicode=False)
    resp = client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf, "application/pdf"),
            "payload": (None, json.dumps({"searches": [{"query": "Dupont"}]}), "application/json"),
        },
    )

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["status"] == "inconclusive"
    assert len(detail["unreliable_fonts"]) == 1
    assert detail["unreliable_fonts"][0]["page"] == 0


@pytest.mark.integration
def test_acknowledging_the_page_lets_the_export_through() -> None:
    """L'utilisateur a vu le texte à l'écran et décide. On ne peut pas le lire à sa place."""
    pdf = _document(identity=True, tounicode=False)
    resp = client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf, "application/pdf"),
            "payload": (
                None,
                json.dumps(
                    {"searches": [{"query": "Dupont"}], "acknowledged_font_pages": [0]}
                ),
                "application/json",
            ),
        },
    )

    assert resp.status_code == 200, resp.text
