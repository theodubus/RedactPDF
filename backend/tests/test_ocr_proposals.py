"""L'OCR propose des zones, il ne garantit rien.

C'est le seul module dont la sortie n'est pas couverte par le contrat, et ces
tests portent surtout sur ce qu'il n'a **pas** le droit de faire : éteindre un
signalement, déverrouiller `block`, ou se faire passer pour un résultat vérifié.

Ignorés si tesseract n'est pas installé. C'est le cas de la CI, et c'est aussi
celui de la plupart des utilisateurs : la fonction se désactive proprement plutôt
que d'échouer à l'export.
"""
from __future__ import annotations

import json
import pathlib

import pymupdf
import pytest
from fastapi.testclient import TestClient

from redactpdf import ocr
from redactpdf.main import app

client = TestClient(app)

pytestmark = pytest.mark.skipif(
    not ocr.is_available(), reason="tesseract absent : la fonction se désactive"
)

TARGET = "Bourdillon"


def _scan_of(text: str) -> bytes:
    """Une page dont le texte n'existe qu'en pixels.

    Rendue depuis un vrai PDF plutôt que dessinée avec PIL : la police est nette
    et à une taille que l'OCR lit, ce qui évite un test qui échoue pour une
    raison sans rapport avec ce qu'il vérifie.
    """
    source = pymupdf.open()
    page = source.new_page()
    page.insert_text((60, 120), text, fontsize=28)
    pix = page.get_pixmap(dpi=200)
    source.close()

    out = pymupdf.open()
    dest = out.new_page()
    dest.insert_image(dest.rect, pixmap=pix)
    data = out.tobytes()
    out.close()
    return data


def _post(pdf: bytes, payload: dict):
    return client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )


@pytest.mark.integration
def test_a_word_only_present_in_pixels_is_proposed() -> None:
    """Le cas d'usage : une règle qui ne trouvait rien trouve, par proposition."""
    pdf = _scan_of(f"Dossier de {TARGET}")

    without = _post(pdf, {"searches": [{"query": TARGET}], "options": {"image_regions": "ignore"}})
    with_ocr = _post(
        pdf,
        {
            "searches": [{"query": TARGET}],
            "options": {"image_regions": "ignore", "ocr_proposals": True},
        },
    )

    assert without.status_code == 200
    assert without.headers["X-Redaction-Ocr-Proposals"] == "0"
    assert with_ocr.status_code == 200
    assert int(with_ocr.headers["X-Redaction-Ocr-Proposals"]) >= 1


@pytest.mark.integration
def test_the_region_is_still_reviewed_when_a_proposal_lands_in_it() -> None:
    """Une proposition ne dispense pas de regarder."""
    pdf = _scan_of(f"Dossier de {TARGET}")

    resp = _post(pdf, {"searches": [{"query": TARGET}], "options": {"ocr_proposals": True}})

    assert resp.status_code == 409, resp.text[:200]
    assert len(resp.json()["detail"]["opaque_regions"]) == 1


@pytest.mark.unit
def test_a_proposal_that_covers_a_region_entirely_still_does_not_silence_it() -> None:
    """L'invariante du module, attaquée là où elle peut céder.

    Écrit d'abord en intégration, où il ne mordait pas : `drop_covered` exige
    qu'un **seul** rectangle contienne la zone entière, et une boîte de mot ne
    couvre jamais une image en entier. Le test passait donc même en branchant les
    propositions sur la couverture, c'est-à-dire en cassant exactement ce qu'il
    prétendait protéger.

    On fabrique donc le cas limite à la main : une proposition qui recouvre
    entièrement la zone. Elle ne doit toujours rien éteindre, sans quoi un
    détecteur approximatif suffirait à faire sauter la relecture humaine que le
    mode `review` existe pour imposer.
    """
    from redactpdf.opaque import find_opaque_regions
    from redactpdf.pipeline import PlanResult, unresolved_opaque_regions, with_ocr_proposals
    from redactpdf.redaction import RedactionRect

    pdf = _scan_of(f"Dossier de {TARGET}")
    region = find_opaque_regions(pdf)[0]
    covering_rect = RedactionRect(
        page=region.page,
        x0=region.bbox[0] - 10,
        y0=region.bbox[1] - 10,
        x1=region.bbox[2] + 10,
        y1=region.bbox[3] + 10,
    )
    empty = PlanResult(manual=[], search=[], regex=[], presets=[], full_page=[], all_rects=[])

    as_proposal = with_ocr_proposals(empty, [covering_rect])
    as_manual = PlanResult(
        manual=[covering_rect],
        search=[],
        regex=[],
        presets=[],
        full_page=[],
        all_rects=[covering_rect],
    )

    still_there = unresolved_opaque_regions(pdf, as_proposal, has_textual_rules=True)
    silenced = unresolved_opaque_regions(pdf, as_manual, has_textual_rules=True)

    assert len(still_there) == 1, "une proposition ne doit jamais éteindre un signalement"
    assert silenced == [], "un rectangle posé à la main, lui, traite bien la zone"
    assert as_proposal.manual == [] and as_proposal.full_page == []


@pytest.mark.integration
def test_the_review_shows_what_was_already_proposed() -> None:
    """L'intérêt annoncé de la combinaison : faire gagner du temps, pas remplacer.

    La proposition apparaît en surimpression, marquée `ocr` et non `manual` : une
    suggestion ne doit pas se lire comme une décision.
    """
    pdf = _scan_of(f"Dossier de {TARGET}")

    resp = _post(pdf, {"searches": [{"query": TARGET}], "options": {"ocr_proposals": True}})

    covered = resp.json()["detail"]["opaque_regions"][0]["covered"]
    assert [a["source"] for a in covered] == ["ocr"]
    x0, y0, x1, y1 = covered[0]["bbox"]
    assert 0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0


@pytest.mark.integration
def test_ocr_does_not_unlock_block_mode() -> None:
    """Une zone parcourue par un détecteur approximatif n'est pas une zone lue."""
    pdf = _scan_of(f"Dossier de {TARGET}")

    resp = _post(
        pdf,
        {
            "searches": [{"query": TARGET}],
            "options": {"image_regions": "block", "ocr_proposals": True},
        },
    )

    assert resp.status_code == 409


@pytest.mark.integration
def test_the_report_says_the_proposals_are_not_covered_by_the_audit() -> None:
    """Un rapport « pass » sans cette mention se lirait comme une garantie totale.

    L'audit relit le **texte** de la sortie ; ce que l'OCR a cru voir dans une
    image n'y a jamais été, donc il ne peut ni le confirmer ni l'infirmer.
    """
    import base64

    pdf = _scan_of(f"Dossier de {TARGET}")
    resp = _post(
        pdf,
        {
            "searches": [{"query": TARGET}],
            "options": {"image_regions": "ignore", "ocr_proposals": True},
        },
    )

    report = json.loads(base64.b64decode(resp.headers["X-Redaction-Audit-Report-B64"]))
    assert report["status"] == "pass"
    assert report["ocr_proposals"]["guaranteed"] is False
    assert report["ocr_proposals"]["count"] >= 1


@pytest.mark.integration
def test_nothing_is_proposed_without_a_textual_rule() -> None:
    """Les propositions viennent des règles appliquées à la couche OCR.

    Sans règle, il n'y a rien à appliquer : l'OCR ne décide pas tout seul de ce
    qui est sensible, et prétendre le contraire serait exactement la promesse que
    ce module refuse de faire.
    """
    pdf = _scan_of(f"Dossier de {TARGET}")

    resp = _post(
        pdf,
        {
            "rects": [{"page": 0, "x0": 10, "y0": 10, "x1": 60, "y1": 40}],
            "options": {"image_regions": "ignore", "ocr_proposals": True},
        },
    )

    assert resp.status_code == 200
    assert resp.headers["X-Redaction-Ocr-Proposals"] == "0"


@pytest.mark.unit
def test_the_feature_disables_itself_without_tesseract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absence de tesseract : rien ne casse, la fonction ne fait simplement rien.

    Le binaire figé vend « un fichier, rien à installer », donc tesseract n'est
    pas embarqué et l'absence est le cas courant, pas l'exception.
    """
    monkeypatch.setattr(ocr, "available_languages", lambda: [])

    assert ocr.is_available() is False
    assert ocr.resolve_language("fra") is None
    assert ocr.propose_from_regions(b"%PDF-", [], searches=[]) == []


@pytest.mark.unit
def test_config_tells_the_ui_whether_it_can_offer_the_option() -> None:
    """Sans cela l'interface proposerait une case qui n'aurait aucun effet."""
    body = client.get("/config").json()

    assert body["ocr_available"] is ocr.is_available()
    assert isinstance(body["ocr_languages"], list)


@pytest.mark.unit
def test_the_language_models_are_the_ones_we_shipped() -> None:
    """Contrat sur les octets, comme pour les fixtures PDF.

    Ces fichiers sont binaires et versionnés. `.gitattributes` les marque
    `binary` précisément parce qu'une conversion de fin de ligne les corromprait
    en silence sur un checkout Windows, et un modèle corrompu ne lève pas : il
    lit mal, ce qui est le pire des deux.
    """
    import hashlib

    directory = pathlib.Path(__file__).resolve().parents[1] / "redactpdf" / "_tessdata"
    expected = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        expected[name.lstrip("*")] = digest

    assert expected, "SHA256SUMS ne doit pas être vide"
    for name, digest in expected.items():
        actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        assert actual == digest, f"{name} ne correspond plus à son empreinte"


@pytest.mark.unit
def test_the_bundled_models_are_preferred_over_a_system_install() -> None:
    """L'embarqué passe devant : c'est le seul dont on connaît la variante.

    Les mesures de qualité citées dans le module portent sur `tessdata_fast`
    version connue ; un tesseract système d'une autre variante les invaliderait
    sans prévenir.
    """
    from redactpdf.paths import bundled_tessdata

    bundled = bundled_tessdata()
    assert bundled is not None, "les modèles doivent voyager avec le paquet"
    assert ocr.tessdata_dir() == str(bundled)
    assert {"fra", "eng"} <= set(ocr.available_languages())


@pytest.mark.unit
def test_a_missing_language_does_not_take_the_others_down_with_it() -> None:
    """Demander une langue absente ferait échouer la reconnaissance entière.

    Tesseract accepte plusieurs modèles séparés par `+` ; on ne garde que ceux
    qui sont là, plutôt que de transmettre une liste dont un élément n'existe pas.
    """
    assert ocr.resolve_language("fra+eng") == "fra+eng"
    assert ocr.resolve_language("deu") == ocr.DEFAULT_LANGUAGE
    assert ocr.resolve_language("fra+deu") == "fra"


@pytest.mark.integration
def test_a_small_image_carrying_a_name_is_not_exported_silently() -> None:
    """La régression du 10 septembre 2026, et le troisième seuil de surface à tomber.

    Ce test affirmait auparavant l'inverse : « le seuil décide de ce qu'on montre,
    pas de ce qu'on lit », donc une petite image donnait un 200 accompagné d'une
    proposition OCR. Le piège construit pour le vérifier a montré que la
    distinction ne tenait pas. Tampon de 60 x 39 points sur une A4, soit 0,467 %,
    portant BOURDILLON en 250 x 163 pixels :

        avant   HTTP 200, audit pass, 0 occurrence, 0 proposition, aucune revue,
                et l'OCR relit « BOURDILLON » dans l'image de sortie
        apres   HTTP 409, la zone est signalée

    L'OCR étant désactivé par défaut, la version d'avant fuyait sur le chemin par
    défaut. Ce que le moteur peut lire et ce qu'il doit signaler ont désormais le
    même seuil.
    """
    source = pymupdf.open()
    page = source.new_page()
    page.insert_text((60, 120), TARGET, fontsize=28)
    pix = page.get_pixmap(dpi=200)
    source.close()

    doc = pymupdf.open()
    dest = doc.new_page()
    # 60 x 30 points sur une A4 : 0,36 % de la page, sous l'ancien seuil de 0,5 %.
    dest.insert_image(pymupdf.Rect(20, 20, 80, 50), pixmap=pix)
    pdf = doc.tobytes()
    doc.close()

    from redactpdf.opaque import find_opaque_regions

    regions = find_opaque_regions(pdf)
    assert len(regions) == 1
    assert regions[0].page_share < 0.005, "sous l'ancien seuil, et signalée quand même"

    # Défauts : pas d'OCR. Le chemin qui fuyait.
    plain = _post(pdf, {"searches": [{"query": TARGET}]})
    assert plain.status_code == 409, plain.text[:200]
    assert plain.json()["detail"]["status"] == "inconclusive"

    # Avec l'OCR, la zone est toujours signalée (une proposition n'éteint jamais
    # une revue) mais la proposition est bien là pour la traiter.
    with_ocr = _post(
        pdf,
        {
            "searches": [{"query": TARGET}],
            "options": {"image_regions": "ignore", "ocr_proposals": True},
        },
    )
    assert with_ocr.status_code == 200, with_ocr.text[:200]
    assert int(with_ocr.headers["X-Redaction-Ocr-Proposals"]) >= 1


def _pattern_document() -> bytes:
    """Un nom peint par un motif de tuilage : visible, absent de la couche texte.

    Construit à la main : aucune API de haut niveau ne pose un motif portant du
    texte. C'est pourtant une forme banale, produite par les outils de mise en
    page pour les fonds et les tampons répétés.
    """
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 300), "texte normal", fontsize=12)
    raw = doc.tobytes()
    doc.close()

    out = pymupdf.open(stream=raw, filetype="pdf")
    pg = out[0]
    font_xref = pg.get_fonts(full=True)[0][0]
    kind, value = out.xref_get_key(pg.xref, "Resources")
    res = int(value.split()[0]) if kind == "xref" else pg.xref

    pattern = out.get_new_xref()
    out.update_object(
        pattern,
        "<< /Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 "
        "/BBox [0 0 220 50] /XStep 220 /YStep 50 "
        f"/Resources << /Font << /F0 {font_xref} 0 R >> >> >>",
    )
    out.update_stream(pattern, f"BT /F0 16 Tf 5 20 Td ({TARGET}) Tj ET".encode(), new=True)
    out.xref_set_key(res, "Pattern", f"<< /P0 {pattern} 0 R >>")

    kind, value = out.xref_get_key(pg.xref, "Contents")
    contents = int(value.strip().lstrip("[").split()[0])
    out.update_stream(
        contents,
        out.xref_stream(contents) + b"\nq /Pattern cs /P0 scn 60 400 300 60 re f Q",
    )
    data = out.tobytes()
    out.close()
    return data


@pytest.mark.integration
def test_a_name_painted_by_a_pattern_is_proposed() -> None:
    """Le trou le plus large qui restait, et il était silencieux.

    Tout ce que la page peint sans que l'extracteur le rapporte échappe aux
    règles **et** à l'audit : texte converti en courbes, étiquettes d'un
    graphique vectoriel, texte peint par un motif. Mesuré sur ce dernier : le nom
    est parfaitement lisible à l'écran, une règle rend zéro occurrence, l'export
    part en 200.

    Deux détections ont été mesurées et écartées avant celle-ci. `get_drawings()`
    rend zéro dessin sur cette page. Et la quantité d'encre ne sépare rien : le
    motif en produit 0,09 % quand un tableau légitime en produit 2,65 %.
    """
    pdf = _pattern_document()
    assert TARGET not in pymupdf.open(stream=pdf, filetype="pdf")[0].get_text()

    sans = _post(pdf, {"searches": [{"query": TARGET}], "options": {"image_regions": "ignore"}})
    avec = _post(
        pdf,
        {
            "searches": [{"query": TARGET}],
            "options": {"image_regions": "ignore", "ocr_proposals": True},
        },
    )

    assert sans.headers["X-Redaction-Ocr-Proposals"] == "0"
    assert int(avec.headers["X-Redaction-Ocr-Proposals"]) >= 1


@pytest.mark.unit
def test_a_plain_text_page_costs_nothing() -> None:
    """Le pré-contrôle existe pour ne pas payer un OCR par page sur tout document.

    Une page dont l'encre se réduit à son texte ne peint rien que les règles ne
    voient déjà : elle est écartée avant le rendu.
    """
    from redactpdf.ocr import pages_with_unreported_marks

    doc = pymupdf.open()
    for index in range(5):
        page = doc.new_page()
        page.insert_text((72, 120), f"page {index}, dossier ordinaire", fontsize=12)
    pdf = doc.tobytes()
    doc.close()

    assert pages_with_unreported_marks(pdf) == []


@pytest.mark.unit
def test_a_hairline_outline_is_not_missed_by_the_probe() -> None:
    """Le pré-contrôle tournait à 36 dpi et devenait myope.

    Un texte détouré en 0,4 pt y tombait à 0,014 % d'encre, sous le seuil, donc
    jamais lu. À 72 dpi il donne 0,25 %, pour 7 ms par page.
    """
    from redactpdf.ocr import pages_with_unreported_marks

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 300), "texte normal", fontsize=12)
    shape = page.new_shape()
    for k in range(9):
        x = 80 + k * 40
        shape.draw_rect(pymupdf.Rect(x, 200, x + 8, 240))
        shape.draw_rect(pymupdf.Rect(x + 10, 210, x + 24, 218))
    shape.finish(color=(0, 0, 0), width=0.4)
    shape.commit()
    pdf = doc.tobytes()
    doc.close()

    assert pages_with_unreported_marks(pdf) == [0]
