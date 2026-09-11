"""Du contenu présent dans le fichier et qu'aucun lecteur n'affiche.

Six formes construites le 10 septembre 2026, à la suite d'une question de Théo
sur les commentaires LaTeX. Les commentaires `%` ne parviennent jamais au PDF,
TeX les retire à la compilation, mais la question visait juste : elle a trouvé
trois trous. État mesuré avant correction :

    A. texte en mode de rendu invisible (3 Tr)   extrait, retiré
    B. blanc sur blanc                           extrait, retiré
    C. recouvert par un aplat opaque             extrait, retiré
    D. hors CropBox                              NON extrait, SURVIT, export 200
    E. hors MediaBox                             NON extrait, SURVIT, export 200
    F. Form XObject jamais invoqué               NON extrait, SURVIT, export 200

A, B et C étaient déjà traités : l'extraction les rend, donc la règle les voit.
D, E et F sont la famille « je n'aurais pas pu le voir, mais je conclus succès » :
ni PyMuPDF ni pypdf ne les extraient, donc l'audit à deux moteurs ne rattrape
rien non plus.

D et E se rattrapent d'un clic chez le destinataire, en élargissant la boîte dans
n'importe quel éditeur. Même forme que le calque masqué, mécanisme différent.

**La sonde naïve ne prouve rien ici.** Chercher la chaîne dans les octets bruts
rend « absent » sur un flux compressé, ce qui a d'abord fait conclure à tort que
les six cas étaient traités. `_anywhere_in` décompresse.
"""
from __future__ import annotations

import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from redactpdf.main import app

client = TestClient(app)
TARGET = "BOURDILLON"


def _anywhere_in(pdf: bytes, needle: str) -> bool:
    """Le texte est-il quelque part dans le fichier, flux décompressés compris."""
    raw = needle.encode()
    if raw in pdf:
        return True
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    try:
        for xref in range(1, doc.xref_length()):
            try:
                if doc.xref_is_stream(xref) and raw in doc.xref_stream(xref):
                    return True
            except Exception:
                pass
            try:
                if raw in doc.xref_object(xref, compressed=False).encode("latin-1", "ignore"):
                    return True
            except Exception:
                pass
    finally:
        doc.close()
    return False


def _page_with(extra: bytes, *, cropbox: str | None = None, prep=None) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 60), "Texte normal de la page", fontname="helv", fontsize=11)
    raw = doc.tobytes()
    doc.close()

    out = pymupdf.open(stream=raw, filetype="pdf")
    pg = out[0]
    if prep is not None:
        prep(out, pg)
    if extra:
        contents = pg.get_contents()[0]
        out.update_stream(contents, out.xref_stream(contents) + b"\n" + extra)
    if cropbox is not None:
        out.xref_set_key(pg.xref, "CropBox", cropbox)
    data = out.tobytes()
    out.close()
    return data


def _apply(pdf: bytes) -> object:
    return client.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf, "application/pdf")},
        data={
            "payload": json.dumps(
                {"searches": [{"query": TARGET}], "options": {"image_regions": "ignore"}}
            )
        },
    )


_TEXT = b"BT /Helv 14 Tf"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("label", "stream"),
    [
        ("invisible", _TEXT + b" 3 Tr 72 400 Td (" + TARGET.encode() + b") Tj ET"),
        (
            "blanc sur blanc",
            b"1 1 1 rg " + _TEXT + b" 72 400 Td (" + TARGET.encode() + b") Tj ET 0 0 0 rg",
        ),
        (
            "recouvert",
            _TEXT
            + b" 72 400 Td ("
            + TARGET.encode()
            + b") Tj ET\n1 1 1 rg 60 390 200 24 re f 0 0 0 rg",
        ),
    ],
)
def test_text_invisible_on_screen_is_still_redacted(label: str, stream: bytes) -> None:
    """Ces trois-là étaient déjà traités : l'extraction les rend, la règle les voit."""
    pdf = _page_with(stream)
    assert _anywhere_in(pdf, TARGET), "le piège doit contenir la cible"

    resp = _apply(pdf)

    assert resp.status_code == 200, resp.text[:200]
    assert resp.headers["X-Redaction-Search-Occurrences"] == "1"
    assert not _anywhere_in(resp.content, TARGET)


@pytest.mark.integration
def test_text_outside_the_cropbox_is_redacted() -> None:
    """Le rognage cache le texte au lecteur, pas au fichier.

    `pdfcrop` pose une CropBox, et le destinataire la retire d'un clic.
    """
    pdf = _page_with(
        _TEXT + b" 72 800 Td (" + TARGET.encode() + b") Tj ET", cropbox="[0 0 595 700]"
    )
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    hidden = TARGET not in doc[0].get_text()
    doc.close()
    assert hidden, "le piège doit être invisible à l'extraction ordinaire"

    resp = _apply(pdf)

    assert resp.status_code == 200, resp.text[:200]
    assert resp.headers["X-Redaction-Search-Occurrences"] == "1"
    assert not _anywhere_in(resp.content, TARGET)


@pytest.mark.integration
def test_text_outside_the_mediabox_is_redacted() -> None:
    """Coordonnées négatives : hors du support lui-même, et pourtant dans le fichier."""
    pdf = _page_with(_TEXT + b" 72 -200 Td (" + TARGET.encode() + b") Tj ET")

    resp = _apply(pdf)

    assert resp.status_code == 200, resp.text[:200]
    assert resp.headers["X-Redaction-Search-Occurrences"] == "1"
    assert not _anywhere_in(resp.content, TARGET)


@pytest.mark.integration
def test_the_page_geometry_is_given_back_untouched() -> None:
    """On élargit pour **lire**, pas pour changer le document.

    Sans restauration, l'export sortirait avec une page plus grande que celle
    qu'on a reçue, ce qui casserait l'impression et la mise en page.
    """
    pdf = _page_with(
        _TEXT + b" 72 800 Td (" + TARGET.encode() + b") Tj ET", cropbox="[0 0 595 700]"
    )
    before = pymupdf.open(stream=pdf, filetype="pdf")
    media_in, crop_in = before[0].mediabox, before[0].cropbox
    before.close()

    resp = _apply(pdf)
    assert resp.status_code == 200, resp.text[:200]

    after = pymupdf.open(stream=resp.content, filetype="pdf")
    try:
        assert after[0].mediabox == media_in
        assert after[0].cropbox == crop_in
    finally:
        after.close()


def _with_xobjects(doc: pymupdf.Document, page: pymupdf.Page) -> None:
    font = page.get_fonts(full=True)[0][0]
    made = {}
    for name, text in (("Used", "VISIBLE_XOBJ"), ("Unused", TARGET)):
        xref = doc.get_new_xref()
        doc.update_object(
            xref,
            "<< /Type /XObject /Subtype /Form /BBox [0 0 300 50] "
            f"/Resources << /Font << /Helv {font} 0 R >> >> >>",
        )
        doc.update_stream(
            xref, b"BT /Helv 14 Tf 5 20 Td (" + text.encode() + b") Tj ET", new=True
        )
        made[name] = xref
    _, resources = doc.xref_get_key(page.xref, "Resources")
    doc.xref_set_key(
        int(str(resources).split()[0]),
        "XObject",
        "<< " + " ".join(f"/{n} {x} 0 R" for n, x in made.items()) + " >>",
    )
    contents = page.get_contents()[0]
    doc.update_stream(contents, doc.xref_stream(contents) + b"\nq 1 0 0 1 100 400 cm /Used Do Q")


@pytest.mark.integration
def test_a_form_xobject_nothing_draws_is_dropped() -> None:
    """Rien ne l'invoque, donc rien ne l'affiche, donc il n'a rien à faire dans la sortie.

    Contrairement au hors-cadrage, il n'y a rien à révéler ici : aucun
    élargissement ne le rendrait visible et l'utilisateur ne pourrait pas le
    viser. On coupe le porteur, comme pour une annotation.
    """
    pdf = _page_with(b"", prep=_with_xobjects)
    assert _anywhere_in(pdf, TARGET)

    resp = _apply(pdf)

    assert resp.status_code == 200, resp.text[:200]
    assert not _anywhere_in(resp.content, TARGET)


@pytest.mark.integration
def test_a_form_xobject_that_is_drawn_survives() -> None:
    """Le garde-fou du correctif ci-dessus : ne jamais retirer du visible."""
    pdf = _page_with(b"", prep=_with_xobjects)

    resp = _apply(pdf)

    assert resp.status_code == 200, resp.text[:200]
    assert _anywhere_in(resp.content, "VISIBLE_XOBJ")
    doc = pymupdf.open(stream=resp.content, filetype="pdf")
    try:
        assert "VISIBLE_XOBJ" in doc[0].get_text()
    finally:
        doc.close()


def _declared_text(visible: str, declared: str) -> bytes:
    """Des glyphes `visible`, un `/ActualText` qui annonce autre chose."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Texte normal de la page", fontname="helv", fontsize=11)
    raw = doc.tobytes()
    doc.close()

    out = pymupdf.open(stream=raw, filetype="pdf")
    contents = out[0].get_contents()[0]
    out.update_stream(
        contents,
        out.xref_stream(contents)
        + b"\n/Span << /ActualText ("
        + declared.encode()
        + b") >> BDC\nBT /Helv 14 Tf 72 400 Td ("
        + visible.encode()
        + b") Tj ET\nEMC\n",
    )
    data = out.tobytes()
    out.close()
    return data


@pytest.mark.integration
def test_a_lying_actual_text_does_not_hide_the_glyphs() -> None:
    """Le dixième trou, et le premier où les **deux** extracteurs partagent l'angle mort.

    Mesuré le 11 septembre 2026 : glyphes `BOURDILLON` parfaitement visibles à
    l'écran, `/ActualText (XXXXXXXXXX)`. PyMuPDF lit `XXXXXXXXXX`, pypdf lit des
    octets illisibles, donc une règle sur le nom rendait zéro occurrence et
    l'export partait en 200 avec le nom toujours là. L'audit à deux moteurs ne
    pouvait rien rattraper : il n'a pas deux angles morts différents ici, il a le
    même deux fois.
    """
    pdf = _declared_text(TARGET, "X" * len(TARGET))
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    fooled = TARGET not in doc[0].get_text()
    doc.close()
    assert fooled, "le piège doit tromper l'extraction"

    resp = _apply(pdf)

    assert resp.status_code == 200, resp.text[:200]
    assert resp.headers["X-Redaction-Search-Occurrences"] == "1"
    assert not _anywhere_in(resp.content, TARGET)


@pytest.mark.integration
def test_a_declared_text_carrying_data_is_cut() -> None:
    """Le sens inverse : rien de visible ne porte le nom, la déclaration si.

    Caviarder les glyphes laissait la chaîne dans le flux. On coupe le porteur,
    comme pour une annotation.

    Ce que couper coûte est mesuré ailleurs : sur 80 documents réels, deux
    portent `/ActualText`, pour de la normalisation typographique (`(ffi)` sur
    une ligature, `<FEFF200B>` sur un espace de largeur nulle). Le cas de la
    ligature reste couvert côté motif, et son test vit dans
    `test_hidden_text.py` sur une vraie police plutôt que sur un littéral de flux,
    où `ﬃ` écrit en UTF-8 serait relu octet par octet en WinAnsi.
    """
    pdf = _declared_text("X" * len(TARGET), TARGET)
    assert _anywhere_in(pdf, TARGET)

    resp = _apply(pdf)

    assert resp.status_code == 200, resp.text[:200]
    # Rien de visible ne disait le nom, donc aucune occurrence à compter.
    assert resp.headers["X-Redaction-Search-Occurrences"] == "0"
    assert not _anywhere_in(resp.content, TARGET)
