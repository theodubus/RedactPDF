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


# ---------------------------------------------------------------------------
# Porteurs trouvés le 11 sept. 2026 par différence d'ensembles : on a soustrait
# de ce module l'énumération des clés de catalogue et de page du format (§7.7.2,
# §7.7.3.3). Les six rendaient HTTP 200, `audit: pass` et `coverage: complete`,
# c'est-à-dire le pire des trois verdicts : non pas « je n'ai pas pu lire », mais
# « j'ai tout lu et c'est propre ».
# ---------------------------------------------------------------------------


def _anywhere_in(pdf_bytes: bytes, needle: str) -> bool:
    """Cherche dans les objets ET dans les flux décompressés.

    Chercher la chaîne dans les octets bruts ne prouve rien : un flux compressé
    la cache sans la retirer. Cette erreur a déjà fait conclure à tort que six
    cas étaient traités, le 10 sept.
    """
    raw = needle.encode()
    if raw in pdf_bytes:
        return True
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        for xref in range(1, doc.xref_length()):
            try:
                if raw in doc.xref_object(xref, compressed=False).encode():
                    return True
            except Exception:
                pass
            try:
                stream = doc.xref_stream(xref)
            except Exception:
                stream = None
            if stream and raw in stream:
                return True
    finally:
        doc.close()
    return False


def _document_with_a_thumbnail() -> bytes:
    """Une page portant la cible, plus sa vignette rendue AVANT caviardage."""
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((40, 100), TARGET, fontname="helv", fontsize=24)
    pix = page.get_pixmap(dpi=120)

    xref = doc.get_new_xref()
    doc.update_object(
        xref,
        "<</Type/XObject/Subtype/Image"
        f"/Width {pix.width}/Height {pix.height}"
        "/ColorSpace/DeviceRGB/BitsPerComponent 8>>",
    )
    doc.update_stream(xref, bytes(pix.samples), new=True, compress=True)
    doc.xref_set_key(page.xref, "Thumb", f"{xref} 0 R")
    out: bytes = doc.tobytes()
    doc.close()
    return out


def _thumbnail_text(pdf_bytes: bytes) -> str | None:
    """Ce qu'un lecteur d'images retrouve dans la vignette, ou None s'il n'y en a plus."""
    from redactpdf.paths import bundled_tessdata

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        kind, value = doc.xref_get_key(doc[0].xref, "Thumb")
        if kind == "null":
            return None
        pix = pymupdf.Pixmap(doc, int(value.split()[0]))
        ocr = pymupdf.open(
            "pdf", pix.pdfocr_tobytes(language="eng", tessdata=str(bundled_tessdata()))
        )
        try:
            return str(ocr[0].get_text().strip())
        finally:
            ocr.close()
    finally:
        doc.close()


@pytest.mark.integration
def test_the_thumbnail_fixture_really_carries_the_target() -> None:
    """Sans ce contrôle, le test suivant passerait sur une vignette illisible.

    Trois pièges de ce projet se sont révélés vides après coup ; celui-ci a
    d'abord été construit avec un flux mal filtré, et l'OCR ne rendait rien.
    """
    assert _thumbnail_text(_document_with_a_thumbnail()) == TARGET


@pytest.mark.integration
def test_a_page_thumbnail_does_not_survive_the_export() -> None:
    """`/Thumb` est le rendu de la page AVANT caviardage.

    Aucun placement dans le flux de contenu, donc `opaque.py` ne peut pas la
    voir : il examine les images dessinées. Mesuré avant correctif : page propre,
    HTTP 200, `coverage: complete`, et l'OCR relisait la cible mot pour mot dans
    la vignette de sortie.
    """
    response = _redact(_document_with_a_thumbnail())
    assert response.status_code == 200
    assert _thumbnail_text(response.content) is None


def _document_with_catalog_carriers() -> bytes:
    """La cible dans cinq porteurs qu'aucune règle ne lit et qu'on ne dessine pas."""
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((40, 100), "rien a voir", fontname="helv", fontsize=14)
    catalog = doc.pdf_catalog()

    piece = doc.get_new_xref()
    doc.update_object(piece, f"<</Private<</Note({TARGET})>>>>")
    doc.xref_set_key(page.xref, "PieceInfo", f"<</MonAppli {piece} 0 R>>")

    doc.xref_set_key(catalog, "PageLabels", f"<</Nums[0<</S/D/P({TARGET} )>>]>>")

    info = doc.get_new_xref()
    doc.update_object(info, f"<</Title({TARGET})/Author({TARGET})>>")
    thread = doc.get_new_xref()
    doc.update_object(thread, f"<</Type/Thread/I {info} 0 R>>")
    doc.xref_set_key(catalog, "Threads", f"[{thread} 0 R]")

    embedded = doc.get_new_xref()
    doc.update_object(embedded, "<</Type/EmbeddedFile>>")
    doc.update_stream(embedded, TARGET.encode(), new=True, compress=True)
    spec = doc.get_new_xref()
    doc.update_object(
        spec,
        f"<</Type/Filespec/F(note.txt)/UF(note.txt)/EF<</F {embedded} 0 R>>>>",
    )
    doc.xref_set_key(page.xref, "AF", f"[{spec} 0 R]")

    doc.add_ocg(TARGET)

    out: bytes = doc.tobytes()
    doc.close()
    return out


@pytest.mark.integration
def test_the_catalog_carriers_fixture_really_carries_the_target() -> None:
    """Sans ce contrôle, le test suivant passerait sur un document vide."""
    assert _anywhere_in(_document_with_catalog_carriers(), TARGET)


@pytest.mark.integration
def test_catalog_and_page_carriers_do_not_survive_the_export() -> None:
    """`/PieceInfo`, `/PageLabels`, `/Threads`, `/AF` et le nom d'un calque.

    `/AF` mérite sa mention : c'est la même pièce jointe que
    `/Names/EmbeddedFiles`, accrochée au catalogue ou à la page, donc
    `embfile_del` ne la voyait pas et le fichier ressortait intact.

    L'assertion porte sur les octets décompressés de la sortie, ce qu'aucune API
    de lecture ne peut contredire.
    """
    response = _redact(_document_with_catalog_carriers())
    assert response.status_code == 200
    assert not _anywhere_in(response.content, TARGET)


# ---------------------------------------------------------------------------
# Second lot du 11 sept. 2026 : fin de l'énumération, plus les entrées « à voir »
# de l'inventaire. Quatre porteurs de plus, et deux soupçons levés.
# ---------------------------------------------------------------------------


def _content_xref(doc: pymupdf.Document, page: pymupdf.Page) -> int:
    """`/Contents` est tantôt un flux, tantôt un tableau de flux."""
    return int(page.get_contents()[0])


def _resources_xref(doc: pymupdf.Document, page: pymupdf.Page) -> int:
    """`/Resources` est souvent indirect, et `xref_set_key` ne traverse pas."""
    kind, value = doc.xref_get_key(page.xref, "Resources")
    if kind == "xref":
        return int(value.split()[0])
    new = doc.get_new_xref()
    doc.update_object(new, value if kind == "dict" else "<<>>")
    doc.xref_set_key(page.xref, "Resources", f"{new} 0 R")
    return new


def _document_with_object_carriers() -> bytes:
    """La cible dans quatre porteurs portés par des objets, pas par des flux."""
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((40, 100), "rien a voir", fontname="helv", fontsize=14)
    catalog = doc.pdf_catalog()

    # 1. liste de propriétés désignée par un opérateur BDC
    prop = doc.get_new_xref()
    doc.update_object(prop, f"<</Type/Note/Contents({TARGET})>>")
    doc.xref_set_key(_resources_xref(doc, page), "Properties", f"<</MC0 {prop} 0 R>>")
    content = _content_xref(doc, page)
    doc.update_stream(content, b"/OC /MC0 BDC\n" + doc.xref_stream(content) + b"\nEMC")

    # 2. arbre de structure balisé
    element = doc.get_new_xref()
    doc.update_object(
        element,
        f"<</Type/StructElem/S/P/Alt({TARGET})/ActualText({TARGET})/T({TARGET})>>",
    )
    root = doc.get_new_xref()
    doc.update_object(root, f"<</Type/StructTreeRoot/K[{element} 0 R]>>")
    doc.xref_set_key(catalog, "StructTreeRoot", f"{root} 0 R")

    # 3. collection (portfolio)
    collection = doc.get_new_xref()
    doc.update_object(collection, f"<</Type/Collection/Schema<</F<</N({TARGET})>>>>>>")
    doc.xref_set_key(catalog, "Collection", f"{collection} 0 R")

    # 4. XMP accroché à la page et non au catalogue
    meta = doc.get_new_xref()
    doc.update_object(meta, "<</Type/Metadata/Subtype/XML>>")
    doc.update_stream(meta, f"<dc:title>{TARGET}</dc:title>".encode(), new=True, compress=True)
    doc.xref_set_key(page.xref, "Metadata", f"{meta} 0 R")

    out: bytes = doc.tobytes()
    doc.close()
    return out


@pytest.mark.integration
def test_the_object_carriers_fixture_really_carries_the_target() -> None:
    """Sans ce contrôle, le test suivant passerait sur un document vide."""
    assert _anywhere_in(_document_with_object_carriers(), TARGET)


@pytest.mark.integration
def test_object_carriers_do_not_survive_the_export() -> None:
    """Quatre porteurs que le nettoyage des flux n'atteint pas.

    `pipeline._strip_declared_text` coupe `/ActualText` dans les *flux* de
    contenu marqué ; l'arbre de structure porte les mêmes clés sur des
    **objets**, et `del_xml_metadata` ne voit que le XMP du catalogue.
    """
    response = _redact(_document_with_object_carriers())
    assert response.status_code == 200
    assert not _anywhere_in(response.content, TARGET)


@pytest.mark.integration
def test_an_optional_content_membership_keeps_its_type() -> None:
    """Le vidage des listes de propriétés ne doit pas toucher la visibilité.

    Une entrée `/Properties` peut désigner un groupe de contenu optionnel : la
    vider changerait ce qui s'affiche, et `all_layers_visible` en dépend. Ce
    test échoue si la garde disparaît.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((40, 100), "rien a voir", fontname="helv", fontsize=14)
    ocg = doc.add_ocg("calque")
    doc.xref_set_key(_resources_xref(doc, page), "Properties", f"<</MC0 {ocg} 0 R>>")
    pdf: bytes = doc.tobytes()
    doc.close()

    response = _redact(pdf)
    assert response.status_code == 200

    out = pymupdf.open(stream=response.content, filetype="pdf")
    try:
        kinds = [
            out.xref_get_key(xref, "Type")[1]
            for xref in range(1, out.xref_length())
            if out.xref_get_key(xref, "Type")[0] == "name"
        ]
        assert "/OCG" in kinds
    finally:
        out.close()


@pytest.mark.integration
def test_a_signature_appearance_does_not_survive_the_export() -> None:
    """Soupçon levé plutôt que correctif : l'apparence part avec l'annotation.

    L'inventaire portait « apparence d'un champ de signature non couverte par le
    retrait des annotations » en `A VOIR` depuis le 10 sept. Mesuré le 11 : elle
    est couverte. Le test existe pour que ça le reste.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    appearance = doc.get_new_xref()
    doc.update_object(
        appearance,
        "<</Type/XObject/Subtype/Form/BBox[0 0 200 50]/Resources<</Font<</F1"
        "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>>>>>>>",
    )
    doc.update_stream(
        appearance,
        f"BT /F1 12 Tf 5 20 Td (Signe par {TARGET}) Tj ET".encode(),
        new=True,
        compress=True,
    )
    widget = doc.get_new_xref()
    doc.update_object(
        widget,
        f"<</Type/Annot/Subtype/Widget/FT/Sig/T(sig1)/Rect[40 40 240 90]"
        f"/AP<</N {appearance} 0 R>>/F 4>>",
    )
    doc.xref_set_key(page.xref, "Annots", f"[{widget} 0 R]")
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", f"<</Fields[{widget} 0 R]/SigFlags 3>>")
    pdf: bytes = doc.tobytes()
    doc.close()

    assert _anywhere_in(pdf, TARGET)
    response = _redact(pdf)
    assert response.status_code == 200
    assert not _anywhere_in(response.content, TARGET)
