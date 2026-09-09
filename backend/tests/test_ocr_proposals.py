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
def test_an_image_below_the_review_threshold_is_still_read() -> None:
    """Le seuil décide de ce qu'on montre, pas de ce qu'on lit.

    Un logo ne mérite pas un écran de relecture, mais il peut porter un nom
    d'employeur, et le lire coûte un dixième de seconde. Mesuré sur une fiche de
    paie réelle : logo de 202 x 122 px, 0,11 s, « REPUBLIQUE FRANCAISE » lu.
    """
    source = pymupdf.open()
    page = source.new_page()
    page.insert_text((60, 120), TARGET, fontsize=28)
    pix = page.get_pixmap(dpi=200)
    source.close()

    doc = pymupdf.open()
    dest = doc.new_page()
    # Un dixième de la largeur : bien en dessous de MIN_PAGE_SHARE, donc jamais
    # signalé à la relecture.
    dest.insert_image(pymupdf.Rect(20, 20, 80, 50), pixmap=pix)
    pdf = doc.tobytes()
    doc.close()

    from redactpdf.opaque import find_opaque_regions

    assert find_opaque_regions(pdf) == [], "cette image doit rester sous le seuil de revue"

    resp = _post(
        pdf,
        {
            "searches": [{"query": TARGET}],
            "options": {"image_regions": "review", "ocr_proposals": True},
        },
    )

    assert resp.status_code == 200, resp.text[:200]
    assert int(resp.headers["X-Redaction-Ocr-Proposals"]) >= 1
