"""Porteurs de texte situés hors du flux de contenu des pages.

Le caviardage nettoie ce qui est dessiné. Un signet, un script de document ou un
paquet XFA transportent du texte que personne ne regarde et qu'aucune règle
géométrique n'atteint. Mesuré avant d'écrire ce module : une règle « Dupont »
nettoyait la page, rendait HTTP 200, et laissait « Dossier Dupont - confidentiel »
dans le volet de navigation.
"""
from __future__ import annotations

import io
import json

import pymupdf
import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from redactpdf.main import app

client = TestClient(app)
TARGET = "Dupont"


def _document_with_carriers() -> bytes:
    """Une page propre, plus la cible cachée dans quatre porteurs différents."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    c.setFont("Helvetica", 12)
    c.drawString(60, height - 80, f"Dossier de Jean {TARGET}")
    c.bookmarkPage("k")
    c.addOutlineEntry(f"Dossier {TARGET} - confidentiel", "k")
    c.showPage()
    c.save()

    doc = pymupdf.open(stream=buf.getvalue(), filetype="pdf")
    catalog = doc.pdf_catalog()

    js = doc.get_new_xref()
    doc.update_object(js, f"<< /S /JavaScript /JS (var client = 'Jean {TARGET}';) >>")
    names = doc.get_new_xref()
    doc.update_object(names, f"<< /JavaScript << /Names [ (a) {js} 0 R ] >> >>")
    doc.xref_set_key(catalog, "Names", f"{names} 0 R")
    doc.xref_set_key(catalog, "OpenAction", f"{js} 0 R")

    xfa = doc.get_new_xref()
    doc.update_object(xfa, "<< >>")
    doc.update_stream(xfa, f"<xfa><client>Jean {TARGET}</client></xfa>".encode())
    acro = doc.get_new_xref()
    doc.update_object(acro, f"<< /XFA {xfa} 0 R /Fields [] >>")
    doc.xref_set_key(catalog, "AcroForm", f"{acro} 0 R")

    out = doc.tobytes()
    doc.close()
    return out


def _redact(pdf: bytes, options: dict | None = None):
    payload: dict = {"searches": [{"query": TARGET}]}
    if options is not None:
        payload["options"] = options
    return client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )


@pytest.mark.integration
def test_the_fixture_really_carries_the_target_everywhere() -> None:
    """Sans ce contrôle, les tests suivants passeraient sur un document vide."""
    pdf = _document_with_carriers()
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    catalog = doc.pdf_catalog()

    assert TARGET in doc.get_toc()[0][1]
    assert doc.xref_get_key(catalog, "Names/JavaScript")[0] != "null"
    assert doc.xref_get_key(catalog, "OpenAction")[0] != "null"
    assert doc.xref_get_key(catalog, "AcroForm/XFA")[0] != "null"
    doc.close()


@pytest.mark.integration
def test_carriers_are_stripped_by_default() -> None:
    """L'assainissement par défaut doit vider les quatre porteurs.

    L'assertion qui compte est la dernière : la chaîne ne doit plus exister
    nulle part dans les octets du fichier, ce qui ne dépend d'aucune API de
    lecture et ne peut pas être contourné par une interprétation.
    """
    resp = _redact(_document_with_carriers())
    assert resp.status_code == 200, resp.text

    out = pymupdf.open(stream=resp.content, filetype="pdf")
    catalog = out.pdf_catalog()
    assert out.get_toc() == []
    assert out.xref_get_key(catalog, "OpenAction")[0] == "null"
    out.close()

    assert TARGET.encode() not in resp.content


@pytest.mark.integration
def test_carriers_survive_when_the_caller_opts_out() -> None:
    """Les porteurs restent si on les désactive : le nettoyage est explicite.

    Ce test existe pour que la suppression ne devienne pas un effet de bord
    silencieux d'autre chose.
    """
    resp = _redact(
        _document_with_carriers(),
        {"remove_outline": False, "remove_document_actions": False},
    )
    assert resp.status_code == 200, resp.text

    out = pymupdf.open(stream=resp.content, filetype="pdf")
    toc = out.get_toc()
    out.close()
    assert toc and TARGET in toc[0][1]


def _document_with_a_commented_annotation() -> bytes:
    """Une note collée, c'est-à-dire une annotation qui porte un popup.

    Rien d'exotique : n'importe quel PDF commenté dans un lecteur courant a cette
    forme, et une convention de stage réelle l'avait.
    """
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "corps du document")
    page.insert_link(
        {
            "kind": pymupdf.LINK_URI,
            "from": pymupdf.Rect(72, 200, 200, 220),
            "uri": f"https://exemple.test/{TARGET}",
        }
    )
    annot = page.add_text_annot((300, 300), f"Note interne sur Jean {TARGET}")
    annot.update()
    out = doc.tobytes()
    doc.close()
    return out


@pytest.mark.integration
def test_a_commented_annotation_does_not_crash_the_export() -> None:
    """Régression : ce document rendait HTTP 500.

    `page.delete_annot(a)` rend l'entrée suivante de la chaîne. Après la
    suppression d'une annotation qui porte un popup, la suivante *est* ce popup,
    détaché de sa page avec son parent : PyMuPDF lève « Annot is not bound to a
    page », l'exception remonte, et la requête entière échoue. Le motif de boucle
    en cause est pourtant celui de la documentation.
    """
    resp = _redact(_document_with_a_commented_annotation())

    assert resp.status_code == 200, resp.text[:300]
    assert TARGET.encode() not in resp.content


@pytest.mark.integration
def test_a_filled_form_field_leaves_nothing_behind() -> None:
    """Le filet coupe `/Annots`, donc il doit couper `/AcroForm/Fields` aussi.

    Sans cela, la valeur saisie d'un widget resterait désignée par le formulaire,
    donc présente dans les octets, alors que la page n'y renvoie plus. Un 500
    devenu une fuite silencieuse serait un mauvais échange.
    """
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "corps du document")
    widget = pymupdf.Widget()
    widget.field_name = "nom"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.rect = pymupdf.Rect(72, 300, 300, 320)
    widget.field_value = f"Jean {TARGET}"
    page.add_widget(widget)
    pdf = doc.tobytes()
    doc.close()

    assert TARGET.encode() in pdf, "le document de test doit vraiment porter la cible"

    resp = _redact(pdf)
    assert resp.status_code == 200, resp.text[:300]
    assert TARGET.encode() not in resp.content
