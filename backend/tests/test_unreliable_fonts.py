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


# --------------------------------------------------------------------------
# Type3
#
# Le second critère du détecteur, longtemps non testé sur une vraie police :
# `_document` ci-dessus fabrique un dictionnaire Type0, jamais un Type3, et une
# première mesure a été faite sur une Helvetica dont on avait simplement réécrit
# `/Subtype` en `/Type3` — une police malformée (pas de `/CharProcs`, pas de
# `/Widths`), dont le comportement d'extraction ne dit rien du cas réel.
#
# Reconstruite valide (CharProcs, Encoding/Differences, Widths, FontMatrix), la
# mesure sépare deux cas selon les codes utilisés :
#
#   codes 65-67, noms de glyphes inconnus   extrait 'ABC'
#   codes 1-3   (sous-ensemble)             extrait '\x01\x02\x03'
#
# MuPDF retombe sur le code comme s'il était du Latin-1 quand le nom de glyphe
# ne lui dit rien. Une Type3 issue d'un sous-ensemble ou d'une numérisation
# numérote ses glyphes à partir de 1 : c'est le second cas, et la règle comme
# l'audit lisent alors des caractères de contrôle. Le détecteur ne peut pas
# distinguer les deux depuis le dictionnaire, et refuse donc les deux.
# --------------------------------------------------------------------------


def _type3_document(*, tounicode: bool) -> bytes:
    """Une Type3 valide, glyphes numérotés à partir de 1 comme un sous-ensemble."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Dossier", fontname="helv", fontsize=12)

    names = ("g1", "g2", "g3")
    procs = {}
    for name in names:
        x = doc.get_new_xref()
        doc.update_object(x, "<< >>")
        # d1 déclare la métrique, puis un rectangle plein tient lieu de glyphe.
        doc.update_stream(x, b"600 0 0 0 700 700 d1 0 0 500 700 re f", new=True)
        procs[name] = x

    charprocs = doc.get_new_xref()
    doc.update_object(
        charprocs, "<< " + " ".join(f"/{n} {x} 0 R" for n, x in procs.items()) + " >>"
    )
    encoding = doc.get_new_xref()
    doc.update_object(
        encoding,
        "<< /Type /Encoding /Differences [ 1 " + " ".join(f"/{n}" for n in names) + " ] >>",
    )

    entries = [
        "/Type /Font",
        "/Subtype /Type3",
        "/Name /T3",
        "/FontBBox [ 0 0 700 700 ]",
        "/FontMatrix [ 0.001 0 0 0.001 0 0 ]",
        f"/CharProcs {charprocs} 0 R",
        f"/Encoding {encoding} 0 R",
        "/FirstChar 1",
        "/LastChar 3",
        "/Widths [ 600 600 600 ]",
    ]
    if tounicode:
        cmap = doc.get_new_xref()
        doc.update_object(cmap, "<< >>")
        doc.update_stream(
            cmap,
            b"/CIDInit /ProcSet findresource begin\n"
            b"12 dict begin begincmap\n"
            b"/CMapName /T3 def /CMapType 2 def\n"
            b"1 begincodespacerange <00> <FF> endcodespacerange\n"
            b"3 beginbfchar <01> <0041> <02> <0042> <03> <0043> endbfchar\n"
            b"endcmap CMapName currentdict /CMap defineresource pop end end",
            new=True,
        )
        entries.append(f"/ToUnicode {cmap} 0 R")

    font = doc.get_new_xref()
    doc.update_object(font, "<< " + " ".join(entries) + " >>")

    _, resources_ref = doc.xref_get_key(page.xref, "Resources")
    doc.xref_set_key(int(str(resources_ref).split()[0]), "Font/T3", f"{font} 0 R")

    contents = page.get_contents()[0]
    doc.update_stream(
        contents,
        doc.xref_stream(contents) + b"\nBT /T3 24 Tf 72 700 Td (\\001\\002\\003) Tj ET",
    )

    out = doc.tobytes()
    doc.close()
    return out


@pytest.mark.unit
def test_a_type3_without_tounicode_is_flagged() -> None:
    pdf = _type3_document(tounicode=False)

    doc = pymupdf.open(stream=pdf, filetype="pdf")
    extracted = doc[0].get_text()
    doc.close()
    # La mesure qui justifie le critère : les trois glyphes ne rendent rien de lisible.
    assert "\x01\x02\x03" in extracted

    fonts = find_unreliable_fonts(pdf)
    assert [(f.page, f.subtype) for f in fonts] == [(0, "Type3")]


@pytest.mark.unit
def test_a_type3_with_tounicode_is_fine() -> None:
    """Même police, même dessin : seule la table de correspondance change."""
    assert find_unreliable_fonts(_type3_document(tounicode=True)) == []


@pytest.mark.integration
def test_a_type3_refuses_the_export() -> None:
    resp = client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", _type3_document(tounicode=False), "application/pdf"),
            "payload": (None, json.dumps({"searches": [{"query": "Dossier"}]}), "application/json"),
        },
    )

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert [f["subtype"] for f in detail["unreliable_fonts"]] == ["Type3"]


@pytest.mark.integration
def test_a_rectangle_over_a_type3_still_removes_the_glyphs() -> None:
    """La porte de sortie : ce qu'on ne sait pas lire, on sait toujours l'effacer.

    Sans règle textuelle il n'y a rien à signaler, donc pas de 409 non plus.
    """
    pdf = _type3_document(tounicode=False)
    resp = client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf, "application/pdf"),
            "payload": (
                None,
                json.dumps({"rects": [{"page": 0, "x0": 60, "y0": 60, "x1": 400, "y1": 130}]}),
                "application/json",
            ),
        },
    )

    assert resp.status_code == 200, resp.text
    doc = pymupdf.open(stream=resp.content, filetype="pdf")
    remaining = doc[0].get_text()
    doc.close()
    assert "\x01\x02\x03" not in remaining
