"""Zones qu'aucune règle textuelle n'a pu lire.

Mesuré le 9 septembre 2026, avant que ce contrôle existe : sur un PDF scanné sans
couche texte, une règle « Dupont » et le preset téléphone rendaient tous deux
HTTP 200, image intacte, donnée lisible à l'oeil. C'est le mode d'échec que
l'accroche du projet déclare impossible, atteint sans le moindre message.
"""
from __future__ import annotations

import base64
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from redactpdf.main import app
from redactpdf.opaque import covered_in_image, find_opaque_regions

client = TestClient(app)


def _png(text: str, size: tuple[int, int] = (900, 200)) -> io.BytesIO:
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((20, 80), text, fill="black")
    buf = io.BytesIO()
    image.save(buf, "PNG")
    buf.seek(0)
    return buf


def _scan() -> bytes:
    """Un scan : le texte n'existe que dans l'image, la page n'a aucune couche texte."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    c.drawImage(ImageReader(_png("Nom : Jean Dupont   Tel : 06 12 34 56 78")),
                40, height - 260, width=500, height=110)
    c.showPage()
    c.save()
    return buf.getvalue()


def _hybrid() -> bytes:
    """Le cas qui a tué la première version du contrôle : texte en dur ET zone scannée.

    Tester « la page a-t-elle du texte » ne détecte rien ici. Le logo, lui, doit
    rester sous le seuil.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    c.setFont("Helvetica", 12)
    c.drawString(60, height - 70, "SOCIETE EXEMPLE SARL")
    c.drawString(60, height - 90, "Client : Marie Martin")
    c.drawImage(ImageReader(_png("Tableau scanne : Jean Dupont")),
                60, height - 320, width=460, height=92)
    c.drawImage(ImageReader(_png("logo", (60, 60))), 480, height - 70, width=40, height=40)
    c.showPage()
    c.save()
    return buf.getvalue()


def _scanned_form() -> bytes:
    """Un formulaire scanné en pleine page, surmonté de quelques champs en dur.

    La forme exacte d'un relevé de notes réel mesuré le 9 septembre 2026 : le
    scan occupe 93,7 % de la page et porte tout le formulaire en pixels (nom de
    l'établissement, titre, en-têtes de colonnes) ; la couche texte ne porte que
    les champs variables, et couvre 18,6 % de la surface du scan.

    La version qui écartait une image dès 5 % de recouvrement rendait ici HTTP
    200 sans rien caviarder.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    c.drawImage(
        ImageReader(_png("POLYTECHNIQUE   BULLETIN   SIGLE  CREDITS  NOTE", (1600, 2100))),
        10, 10, width=width - 20, height=height - 20,
    )
    c.setFont("Helvetica", 10)
    # Les champs variables, en dur, épars sur le scan.
    for i in range(9):
        c.drawString(40, height - 90 - i * 70, "Jean Dupont" + " x" * 30)
    c.showPage()
    c.save()
    return buf.getvalue()


def _post(pdf: bytes, payload: dict):
    return client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )


@pytest.mark.integration
def test_a_scan_no_longer_exports_silently() -> None:
    """Le trou d'origine. 409, pas 200."""
    resp = _post(_scan(), {"searches": [{"query": "Dupont"}]})

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["status"] == "inconclusive"
    assert len(detail["opaque_regions"]) == 1
    assert detail["unreliable_fonts"] == []


@pytest.mark.integration
def test_only_the_scanned_block_is_reported_on_a_hybrid_page() -> None:
    """Le tableau scanné est signalé, le logo non : le seuil de taille les sépare."""
    resp = _post(_hybrid(), {"searches": [{"query": "Dupont"}]})

    assert resp.status_code == 409, resp.text
    regions = resp.json()["detail"]["opaque_regions"]
    assert len(regions) == 1
    assert regions[0]["page_share"] > 0.05


@pytest.mark.integration
def test_nothing_is_reported_without_a_textual_rule() -> None:
    """Sans règle textuelle, rien n'a été promis, donc rien n'est à signaler."""
    resp = _post(_scan(), {"rects": [{"page": 0, "x0": 50, "y0": 50, "x1": 100, "y1": 100}]})

    assert resp.status_code == 200, resp.text


@pytest.mark.integration
def test_ignore_mode_is_an_explicit_choice() -> None:
    """`ignore` rend le fichier : c'est un choix nommé, pas un repli silencieux."""
    resp = _post(
        _scan(),
        {"searches": [{"query": "Dupont"}], "options": {"image_regions": "ignore"}},
    )

    assert resp.status_code == 200, resp.text


@pytest.mark.integration
def test_review_mode_accepts_an_acknowledgement() -> None:
    """L'humain a regardé la zone : l'export part."""
    pdf = _scan()
    first = _post(pdf, {"searches": [{"query": "Dupont"}]})
    box = first.json()["detail"]["opaque_regions"][0]["bbox"]

    resp = _post(
        pdf,
        {"searches": [{"query": "Dupont"}], "acknowledged_regions": [{"page": 0, "bbox": box}]},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
def test_block_mode_ignores_acknowledgements() -> None:
    """`block` est le mode non interactif : un script ne clique pas.

    Seule une règle géométrique y déverrouille. Si l'acquittement suffisait,
    `block` ne serait qu'un `review` avec un autre nom.
    """
    pdf = _scan()
    first = _post(pdf, {"searches": [{"query": "Dupont"}]})
    box = first.json()["detail"]["opaque_regions"][0]["bbox"]

    resp = _post(
        pdf,
        {
            "searches": [{"query": "Dupont"}],
            "options": {"image_regions": "block"},
            "acknowledged_regions": [{"page": 0, "bbox": box}],
        },
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.integration
def test_a_geometric_rule_covering_the_region_unlocks_block_mode() -> None:
    """Dessiner dessus traite la zone, et l'éteint même en mode le plus strict."""
    pdf = _scan()
    first = _post(pdf, {"searches": [{"query": "Dupont"}]})
    x0, y0, x1, y1 = first.json()["detail"]["opaque_regions"][0]["bbox"]

    resp = _post(
        pdf,
        {
            "searches": [{"query": "Dupont"}],
            "options": {"image_regions": "block"},
            "rects": [{"page": 0, "x0": x0, "y0": y0, "x1": x1, "y1": y1}],
        },
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
def test_a_rectangle_that_does_not_quite_cover_still_reports() -> None:
    """Régression : le seuil par ratio de surface laissait passer une bande lisible.

    La première version acceptait une couverture de 95 % de la *surface*. Mesuré
    sur une zone de 320 x 120 pt, cela laissait dépasser une bande de 16 pt de
    large sur toute la hauteur, soit trois caractères en corps 9, sans un mot.
    La surface ignore la forme ; on exige donc un rectangle qui contienne la zone.
    """
    pdf = _scan()
    first = _post(pdf, {"searches": [{"query": "Dupont"}]})
    x0, y0, x1, y1 = first.json()["detail"]["opaque_regions"][0]["bbox"]

    resp = _post(
        pdf,
        {
            "searches": [{"query": "Dupont"}],
            "options": {"image_regions": "block"},
            # Il manque seize points sur la droite.
            "rects": [{"page": 0, "x0": x0, "y0": y0, "x1": x1 - 16, "y1": y1}],
        },
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.integration
def test_a_scanned_form_under_a_text_layer_is_still_reported() -> None:
    """Régression : le ratio de texte écartait un scan pleine page.

    Le critère « au-delà de 5 % de recouvrement, l'image est un fond » a été
    retiré. Un ratio de surface ignore la forme : 18,6 % de la zone sous une
    ligne de texte ne dit rien des 81,4 % que personne n'a lus. Le seul critère
    restant est la taille.
    """
    resp = _post(_scanned_form(), {"searches": [{"query": "Dupont"}]})

    assert resp.status_code == 409, resp.text
    regions = resp.json()["detail"]["opaque_regions"]
    assert len(regions) == 1
    assert regions[0]["page_share"] > 0.9
    # Le ratio reste reporté : il informe, il ne filtre plus.
    assert regions[0]["text_ratio"] > 0.05


@pytest.mark.unit
def test_the_same_image_on_several_pages_shares_one_digest() -> None:
    """Un bandeau répété est la même image : l'empreinte permet de ne la montrer qu'une fois.

    Sans cela, retirer le critère de recouvrement rendrait un document de trente
    pages illisible en revue, ce qui reviendrait à le rendre inutilisable.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    banner = ImageReader(_png("EN-TETE CONFIDENTIEL"))
    for _ in range(3):
        c.drawImage(banner, 40, height - 160, width=500, height=110)
        c.showPage()
    c.save()

    regions = find_opaque_regions(buf.getvalue())

    assert [r.page for r in regions] == [0, 1, 2]
    assert len({r.digest for r in regions}) == 1
    assert regions[0].digest != ""


@pytest.mark.integration
def test_the_409_carries_the_image_pixels_not_the_page_region() -> None:
    """La vignette est l'image seule, pas la région de page.

    Rendre la région composerait par dessus la couche texte, et cette couche est
    exactement ce que les règles ont su lire. Le relecteur y verrait du texte net,
    en conclurait « lisible, rien de caché », et passerait à côté du seul objet
    sur lequel on ne peut rien affirmer.

    Le contrôle porte sur les dimensions : la vignette a le rapport d'aspect de
    l'image (900 x 200, soit 4,5), pas celui de la page A4 (0,707).
    """
    resp = _post(_scan(), {"searches": [{"query": "Dupont"}]})
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]

    digest = detail["opaque_regions"][0]["digest"]
    preview = detail["previews"][digest]
    assert preview["mime"] == "image/jpeg"

    image = Image.open(io.BytesIO(base64.b64decode(preview["data"])))
    assert abs(image.width / image.height - 900 / 200) < 0.05
    assert abs(image.width / image.height - A4[0] / A4[1]) > 1.0


@pytest.mark.integration
def test_one_preview_per_distinct_image_not_per_region() -> None:
    """Un bandeau répété, ce sont N zones et un seul lot de pixels à transporter."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    banner = ImageReader(_png("EN-TETE"))
    for _ in range(3):
        c.drawImage(banner, 40, height - 160, width=500, height=110)
        c.showPage()
    c.save()

    resp = _post(buf.getvalue(), {"searches": [{"query": "Dupont"}]})
    detail = resp.json()["detail"]
    assert len(detail["opaque_regions"]) == 3
    assert len(detail["previews"]) == 1


@pytest.mark.integration
def test_a_rectangle_lands_where_it_belongs_inside_the_image() -> None:
    """Le rectangle déjà posé est situé dans le repère de l'image, normalisé.

    Le scan occupe (40, h-260) a (540, h-150) en points ; un rectangle sur son
    quart haut gauche doit ressortir en [0, 0, 0.5, 0.5] a la tolerance pres. Une
    regle de trois donnerait le meme resultat ici, mais pas sur une image posee
    tournee : c'est l'inverse de la matrice de placement qui est utilise.
    """
    pdf = _scan()
    first = _post(pdf, {"searches": [{"query": "Dupont"}]})
    x0, y0, x1, y1 = first.json()["detail"]["opaque_regions"][0]["bbox"]

    resp = _post(
        pdf,
        {
            "searches": [{"query": "Dupont"}],
            "rects": [
                {
                    "page": 0,
                    "x0": x0,
                    "y0": y0,
                    "x1": x0 + (x1 - x0) / 2,
                    "y1": y0 + (y1 - y0) / 2,
                }
            ],
        },
    )
    assert resp.status_code == 409, resp.text
    covered = resp.json()["detail"]["opaque_regions"][0]["covered"]

    assert len(covered) == 1
    assert covered[0]["source"] == "manual"
    box = covered[0]["bbox"]
    assert box[0] == pytest.approx(0.0, abs=0.02)
    assert box[1] == pytest.approx(0.0, abs=0.02)
    assert box[2] == pytest.approx(0.5, abs=0.02)
    assert box[3] == pytest.approx(0.5, abs=0.02)


@pytest.mark.unit
def test_a_rotated_image_needs_the_inverse_matrix_not_a_rule_of_three() -> None:
    """Une image posée tournée : la règle de trois placerait le rectangle ailleurs.

    L'image est posée après une rotation d'un quart de tour. Le quart *bas gauche*
    de la page correspond alors au quart *haut gauche* de l'image. Une règle de
    trois sur la boîte englobante rendrait le quart bas gauche, c'est-à-dire un
    rectangle vert affiché sur une partie de l'image que rien ne couvre : le
    relecteur croirait traitée une zone qui ne l'est pas.
    """
    im = Image.new("RGB", (400, 200), "white")
    ImageDraw.Draw(im).rectangle([0, 0, 100, 50], fill="red")
    src = io.BytesIO()
    im.save(src, "PNG")
    src.seek(0)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.saveState()
    c.translate(300, 400)
    c.rotate(90)
    c.drawImage(ImageReader(src), 0, 0, width=300, height=150)
    c.restoreState()
    c.showPage()
    c.save()

    region = find_opaque_regions(buf.getvalue())[0]
    x0, y0, x1, y1 = region.bbox
    bottom_left = (x0, (y0 + y1) / 2, (x0 + x1) / 2, y1)

    covered = covered_in_image(region, [(0, bottom_left)])

    assert len(covered) == 1
    assert covered[0]["bbox"] == pytest.approx([0.0, 0.0, 0.5, 0.5], abs=0.02)
