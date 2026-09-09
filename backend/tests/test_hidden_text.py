"""Du texte que le moteur ne voyait pas, sous deux formes.

Les deux ont été trouvés en construisant des pièges le 9 septembre 2026, pas en
relisant le code. Le premier était un **échec silencieux** (règle aveugle, audit
aveugle, export en 200 avec le nom lisible), le second un refus honnête mais sans
issue pour l'utilisateur.
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


def _with_tounicode(text: str, mapping: dict[str, str]) -> bytes:
    """Un PDF dont les glyphes disent une chose et `/ToUnicode` une autre.

    C'est ce que produisent LaTeX, InDesign et Word dès qu'un mot contient ff, fi
    ou fl : un glyphe unique, dont la table déclare U+FB03 et non « ffi ». On ne
    peut pas fabriquer le cas avec `insert_text`, qui remplace les caractères que
    la police de base ne connaît pas.
    """
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 120), text, fontsize=14, fontname="helv")
    raw = doc.tobytes()
    doc.close()

    out = pymupdf.open(stream=raw, filetype="pdf")
    font_xref = out[0].get_fonts(full=True)[0][0]
    entries = "\n".join(
        f"<{ord(code):04X}> <{''.join(f'{ord(ch):04X}' for ch in shown)}>"
        for code, shown in mapping.items()
    )
    cmap = (
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        "1 begincodespacerange <00> <FF> endcodespacerange\n"
        f"{len(mapping)} beginbfchar\n{entries}\nendbfchar\n"
        "endcmap CMapName currentdict /CMap defineresource pop end end"
    )
    xref = out.get_new_xref()
    out.update_object(xref, "<< >>")
    out.update_stream(xref, cmap.encode(), new=True)
    out.xref_set_key(font_xref, "ToUnicode", f"{xref} 0 R")
    data = out.tobytes()
    out.close()
    return data


LIGATURES = [
    pytest.param("Cabinet Grizth et associes", {"z": "ﬃ"}, "Griffith", id="ffi"),
    pytest.param("Dossier Soza Martin", {"z": "ﬁ"}, "Sofia", id="fi"),
    pytest.param("Societe Duzot", {"z": "ﬂ"}, "Duflot", id="fl"),
    pytest.param("Dossier de Lqtitia", {"q": "æ"}, "Laetitia", id="ae"),
    pytest.param("Le cqur du dossier", {"q": "œ"}, "coeur", id="oe"),
]

PATHS = [
    pytest.param({"whole_word": True, "ignore_accents": True}, id="mot-entier"),
    pytest.param({"whole_word": False, "ignore_accents": True}, id="sous-mot"),
    pytest.param({"whole_word": False, "ignore_accents": False}, id="chemin-rapide"),
]


@pytest.mark.integration
@pytest.mark.parametrize("text,mapping,query", LIGATURES)
@pytest.mark.parametrize("options", PATHS)
def test_a_glyph_carrying_several_letters_is_still_found(
    text: str, mapping: dict[str, str], query: str, options: dict
) -> None:
    """Un seul glyphe pour plusieurs lettres, et la requête reste celle qu'on tape.

    Le repliage doit rendre autant de caractères qu'il en reçoit, il ne peut donc
    pas développer « ﬃ » en « ffi ». L'ancienne version en gardait la première
    lettre : « Griﬃth » devenait « Grifth » et « Griffith » ne correspondait plus.
    C'est le **motif** qui s'élargit désormais, en alternance.

    Les trois chemins de recherche sont couverts : ils construisent leur motif
    séparément, et n'en corriger qu'un laisserait le trou ouvert ailleurs.
    """
    pdf = _with_tounicode(text, mapping)
    glyph = next(iter(mapping.values()))
    assert glyph in _text(pdf), "le piège doit vraiment porter le glyphe soudé"

    resp = _post(pdf, {"searches": [{"query": query, "options": options}]})

    assert resp.status_code == 200, resp.text[:200]
    assert int(resp.headers["X-Redaction-Search-Occurrences"]) == 1
    assert glyph not in _text(resp.content), "le nom est resté lisible à l'écran"


@pytest.mark.integration
def test_typing_the_glyph_itself_also_works() -> None:
    """La tolérance va dans les deux sens : le motif accepte les deux écritures."""
    pdf = _with_tounicode("Cabinet Grizth", {"z": "ﬃ"})

    resp = _post(pdf, {"searches": [{"query": "Griﬃth"}]})

    assert resp.status_code == 200
    assert "ﬃ" not in _text(resp.content)


def _hidden_layer_document() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    ocg = doc.add_ocg("calque masqué", on=False)
    page.insert_text((72, 120), "Dossier de Bourdillon", fontsize=14, oc=ocg)
    page.insert_text((72, 200), "Texte visible normal", fontsize=14)
    out = doc.tobytes()
    doc.close()
    return out


@pytest.mark.integration
def test_text_on_a_layer_that_is_off_is_still_redacted() -> None:
    """Un calque éteint cache le texte à l'extraction, pas au lecteur.

    `get_text()` respecte l'état du calque, donc la règle rendait zéro rectangle.
    Seul l'audit à deux moteurs rattrapait, en refusant l'export : honnête, mais
    sans issue, puisqu'on ne peut pas dessiner un rectangle sur un texte qu'on ne
    voit pas. Or n'importe quel lecteur rallume ce calque d'un clic.
    """
    resp = _post(_hidden_layer_document(), {"searches": [{"query": "Bourdillon"}]})

    assert resp.status_code == 200, resp.text[:200]
    assert int(resp.headers["X-Redaction-Search-Occurrences"]) == 1
    assert b"Bourdillon" not in resp.content


@pytest.mark.integration
def test_making_layers_visible_does_not_redact_more_than_asked() -> None:
    """Allumer les calques révèle, ça ne caviarde pas : le reste doit survivre."""
    resp = _post(_hidden_layer_document(), {"searches": [{"query": "Bourdillon"}]})

    assert "Texte visible normal" in _text(resp.content)


@pytest.mark.integration
def test_the_tolerance_does_not_match_a_different_word() -> None:
    """Élargir le motif ne doit pas élargir ce qu'on retire.

    Ce test a attrapé une vraie régression en cours de route. Le repliage gardait
    la première lettre des ligatures, donc « ﬃ » devenait « f », et l'alternance
    se repliait en `(?:ffi|f)` : une requête « Griffith » caviardait « Grifth »,
    un mot qui n'est pas le mot cherché. Pire, la recherche et l'audit ne le
    voyaient pas pareil, et l'export était refusé pour une cible absente.
    """
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 120), "Cabinet Grifth et associes", fontsize=14)
    pdf = doc.tobytes()
    doc.close()

    resp = _post(pdf, {"searches": [{"query": "Griffith"}]})

    assert resp.status_code == 200, resp.text[:200]
    assert resp.headers["X-Redaction-Search-Occurrences"] == "0"
    assert "Grifth" in _text(resp.content)


@pytest.mark.unit
def test_the_folding_rule_exists_once() -> None:
    """Garde-fou structurel : une règle dupliquée est une règle qui dérivera.

    Elle a existé en quatre copies, et n'en corriger que trois a fait dire à la
    recherche et à l'audit deux choses différentes du même document. Le décompte
    est grossier mais il mord : toute nouvelle copie le fait échouer.
    """
    import pathlib as _pathlib

    package = _pathlib.Path(__file__).resolve().parents[1] / "redactpdf"
    holders = [
        path.name
        for path in package.glob("*.py")
        if "NFKD" in path.read_text(encoding="utf-8")
    ]

    assert holders == ["folding.py"], f"le repliage est redéfini dans {holders}"
