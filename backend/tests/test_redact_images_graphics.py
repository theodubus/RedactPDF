from __future__ import annotations

import json
from pathlib import Path

import pymupdf  # PyMuPDF
import pytest
from fastapi.testclient import TestClient

from redactpdf.main import app
from redactpdf.redaction import RedactionRect, redact_pdf_by_rectangles

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "generated"
client = TestClient(app)


def _read_fixture(name: str) -> bytes:
    path = FIXTURES_DIR / name
    return path.read_bytes()


def _count_page_images(pdf_bytes: bytes, page_index: int = 0) -> int:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[page_index]
        return len(page.get_images(full=True))
    finally:
        doc.close()


def _first_image_rect(pdf_bytes: bytes, page_index: int = 0) -> tuple[int, pymupdf.Rect]:
    """Return (xref, rect) for the first image occurrence on the page."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[page_index]
        images = page.get_images(full=True)
        assert images, "Fixture expected to contain at least one image."
        xref = images[0][0]
        rects = page.get_image_rects(xref)
        assert rects, "Image xref found but no rects returned."
        return xref, rects[0]
    finally:
        doc.close()


def _count_drawings(pdf_bytes: bytes, page_index: int = 0) -> int:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[page_index]
        return len(page.get_drawings())
    finally:
        doc.close()


def _first_drawing_rect(pdf_bytes: bytes, page_index: int = 0) -> pymupdf.Rect:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[page_index]
        drawings = page.get_drawings()
        assert drawings, "Fixture expected to contain at least one vector drawing."
        rect = drawings[0].get("rect")
        assert rect is not None, 'Expected drawing dict to contain key "rect".'
        return rect
    finally:
        doc.close()


def _post_redact_rectangles(
    pdf_in: bytes,
    rects: list[RedactionRect],
    *,
    image_mode: str,
    apply_graphics: bool
):
    payload = {
        "rects": [
            {"page": r.page, "x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1}
            for r in rects
        ],
        "options": {
            "image_mode": image_mode,
            "apply_graphics": apply_graphics,
        },
        "audit": {
            "patterns": ["__NEVER_MATCH_123456789__"],
            "regex": False,
            "case_sensitive": True,
        },
    }

    files = {
        "file": ("input.pdf", pdf_in, "application/pdf"),
        "payload": (None, json.dumps(payload), "application/json"),
    }
    return client.post("/redact/apply", files=files)


@pytest.mark.integration
def test_apply_images_removes_overlapping_images() -> None:
    pdf_in = _read_fixture("004_bitmap_image.pdf")

    before = _count_page_images(pdf_in, page_index=0)
    assert before > 0

    _, img_rect = _first_image_rect(pdf_in, page_index=0)
    rect = RedactionRect(page=0, x0=img_rect.x0, y0=img_rect.y0, x1=img_rect.x1, y1=img_rect.y1)

    # Control: image_mode="none" -> should not reduce referenced images
    pdf_keep = redact_pdf_by_rectangles(
        pdf_in,
        [rect],
        image_mode="none",
        apply_graphics=False,
    )
    after_keep = _count_page_images(pdf_keep, page_index=0)
    assert after_keep == before

    # image_mode="remove" -> referenced images should decrease
    pdf_removed = redact_pdf_by_rectangles(
        pdf_in,
        [rect],
        image_mode="remove",
        apply_graphics=False,
    )
    after_removed = _count_page_images(pdf_removed, page_index=0)
    assert after_removed < before


@pytest.mark.integration
def test_apply_graphics_removes_overlapping_vector_drawings() -> None:
    pdf_in = _read_fixture("005_vector_graphics_and_text.pdf")

    before = _count_drawings(pdf_in, page_index=0)
    assert before > 0

    drawing_rect = _first_drawing_rect(pdf_in, page_index=0)
    rect = RedactionRect(
        page=0,
        x0=drawing_rect.x0,
        y0=drawing_rect.y0,
        x1=drawing_rect.x1,
        y1=drawing_rect.y1,
    )

    # Control: graphics disabled -> should not reduce drawings
    pdf_keep = redact_pdf_by_rectangles(
        pdf_in,
        [rect],
        image_mode="none",
        apply_graphics=False,
    )
    after_keep = _count_drawings(pdf_keep, page_index=0)
    assert after_keep >= before  # peut augmenter (blackout)

    # Enable graphics removal -> should reduce drawings
    pdf_removed = redact_pdf_by_rectangles(
        pdf_in,
        [rect],
        image_mode="none",
        apply_graphics=True,
    )
    after_removed = _count_drawings(pdf_removed, page_index=0)
    assert after_removed < after_keep  # must remove drawings vs the keep case


@pytest.mark.integration
def test_api_rectangles_propagates_apply_images() -> None:
    pdf_in = _read_fixture("004_bitmap_image.pdf")
    before = _count_page_images(pdf_in, page_index=0)
    assert before > 0

    _, img_rect = _first_image_rect(pdf_in, page_index=0)
    rect = RedactionRect(page=0, x0=img_rect.x0, y0=img_rect.y0, x1=img_rect.x1, y1=img_rect.y1)

    # Control: image_mode="none"
    resp_keep = _post_redact_rectangles(
        pdf_in, [rect], image_mode="none", apply_graphics=False
    )
    assert resp_keep.status_code == 200
    pdf_keep = resp_keep.content
    assert _count_page_images(pdf_keep, page_index=0) == before

    # image_mode="remove"
    resp_removed = _post_redact_rectangles(
        pdf_in, [rect], image_mode="remove", apply_graphics=False
    )
    assert resp_removed.status_code == 200
    pdf_removed = resp_removed.content
    assert _count_page_images(pdf_removed, page_index=0) < before


@pytest.mark.integration
def test_api_rectangles_propagates_apply_graphics() -> None:
    pdf_in = _read_fixture("005_vector_graphics_and_text.pdf")
    before = _count_drawings(pdf_in, page_index=0)
    assert before > 0

    drawing_rect = _first_drawing_rect(pdf_in, page_index=0)
    rect = RedactionRect(
                    page=0,
                    x0=drawing_rect.x0,
                    y0=drawing_rect.y0,
                    x1=drawing_rect.x1,
                    y1=drawing_rect.y1
                )

    # Control: apply_graphics=False
    resp_keep = _post_redact_rectangles(
        pdf_in, [rect], image_mode="none", apply_graphics=False
    )
    assert resp_keep.status_code == 200
    pdf_keep = resp_keep.content
    after_keep = _count_drawings(pdf_keep, page_index=0)
    assert after_keep >= before  # peut augmenter (blackout)

    # Now enable apply_graphics=True
    resp_removed = _post_redact_rectangles(
        pdf_in, [rect], image_mode="none", apply_graphics=True
    )
    assert resp_removed.status_code == 200
    pdf_removed = resp_removed.content
    after_removed = _count_drawings(pdf_removed, page_index=0)
    assert after_removed < after_keep


def _render_clip(pdf_bytes: bytes, page_index: int, clip: pymupdf.Rect) -> pymupdf.Pixmap:
    """
    Render the page region at 3x DPI to avoid sub-pixel anti-aliasing artifacts
    at the redaction boundary that show up at 1x.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[page_index]
        return page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(3.0, 3.0))
    finally:
        doc.close()


def _is_all_black(pix: pymupdf.Pixmap) -> bool:
    n = pix.n
    samples = pix.samples
    color_channels = n - 1 if pix.alpha else n
    for offset in range(0, len(samples), n):
        for c in range(color_channels):
            if samples[offset + c] != 0:
                return False
    return True


def _has_non_black_pixel(pix: pymupdf.Pixmap) -> bool:
    return not _is_all_black(pix)


def _shrink(rect: pymupdf.Rect, pad: float = 1.0) -> pymupdf.Rect:
    """Inset a rect on all sides; lets us sample interior pixels and dodge edge AA."""
    return pymupdf.Rect(rect.x0 + pad, rect.y0 + pad, rect.x1 - pad, rect.y1 - pad)


@pytest.mark.integration
def test_image_mode_pixels_blackens_only_intersected_region() -> None:
    """
    image_mode="pixels": only the intersected region of an image must become black.
    The rest of the image stays visible (modulo lossy re-encoding).
    The image count must NOT decrease (we don't remove the image, just rewrite pixels).
    """
    pdf_in = _read_fixture("004_bitmap_image.pdf")
    before = _count_page_images(pdf_in, page_index=0)
    assert before > 0

    _, img_rect = _first_image_rect(pdf_in, page_index=0)

    # Cible la moitié gauche de l'image
    half_w = (img_rect.x1 - img_rect.x0) / 2
    left_rect = pymupdf.Rect(img_rect.x0, img_rect.y0, img_rect.x0 + half_w, img_rect.y1)
    right_rect = pymupdf.Rect(img_rect.x0 + half_w, img_rect.y0, img_rect.x1, img_rect.y1)

    redact = RedactionRect(
        page=0, x0=left_rect.x0, y0=left_rect.y0, x1=left_rect.x1, y1=left_rect.y1
    )

    # Sanity: l'image originale a bien des pixels non-noirs des deux côtés
    assert _has_non_black_pixel(_render_clip(pdf_in, 0, _shrink(left_rect)))
    assert _has_non_black_pixel(_render_clip(pdf_in, 0, _shrink(right_rect)))

    pdf_out = redact_pdf_by_rectangles(
        pdf_in,
        [redact],
        image_mode="pixels",
        apply_graphics=False,
    )

    # L'image n'est PAS retirée du PDF
    assert _count_page_images(pdf_out, page_index=0) == before

    # La moitié gauche est entièrement noire ; la droite a encore du contenu.
    # On inset les rects pour ignorer les artefacts d'anti-aliasing au bord.
    assert _is_all_black(_render_clip(pdf_out, 0, _shrink(left_rect)))
    assert _has_non_black_pixel(_render_clip(pdf_out, 0, _shrink(right_rect)))


@pytest.mark.integration
def test_image_mode_pixels_via_api() -> None:
    """
    End-to-end: /redact/apply with image_mode='pixels' on a PARTIAL image rect.
    The image must remain referenced (only pixels are rewritten), and the
    redacted portion must render black.
    Note: when the redact rect covers 100% of the image, PyMuPDF removes the
    image entirely as an optimisation, see test_image_mode_pixels_full_image.
    """
    pdf_in = _read_fixture("004_bitmap_image.pdf")
    before = _count_page_images(pdf_in, page_index=0)
    _, img_rect = _first_image_rect(pdf_in, page_index=0)

    half_w = (img_rect.x1 - img_rect.x0) / 2
    left_rect = pymupdf.Rect(img_rect.x0, img_rect.y0, img_rect.x0 + half_w, img_rect.y1)
    rect = RedactionRect(
        page=0, x0=left_rect.x0, y0=left_rect.y0, x1=left_rect.x1, y1=left_rect.y1
    )

    resp = _post_redact_rectangles(
        pdf_in, [rect], image_mode="pixels", apply_graphics=False
    )
    assert resp.status_code == 200, resp.text

    pdf_out = resp.content
    # Image still referenced: pixels mode keeps the image when only partially covered.
    assert _count_page_images(pdf_out, page_index=0) == before

    # The redacted half is black ; the kept half still has content.
    assert _is_all_black(_render_clip(pdf_out, 0, _shrink(left_rect)))


@pytest.mark.integration
def test_image_mode_pixels_full_image_optimised_to_removal() -> None:
    """
    When image_mode='pixels' and the rect covers the whole image, PyMuPDF
    optimises by dropping the image entirely. The end result is still secure
    (no original content remains). This test pins the current behaviour.
    """
    pdf_in = _read_fixture("004_bitmap_image.pdf")
    before = _count_page_images(pdf_in, page_index=0)
    _, img_rect = _first_image_rect(pdf_in, page_index=0)
    rect = RedactionRect(
        page=0, x0=img_rect.x0, y0=img_rect.y0, x1=img_rect.x1, y1=img_rect.y1
    )

    pdf_out = redact_pdf_by_rectangles(
        pdf_in, [rect], image_mode="pixels", apply_graphics=False
    )
    after = _count_page_images(pdf_out, page_index=0)
    assert after < before, "PyMuPDF should drop the image when fully covered."
    assert _is_all_black(_render_clip(pdf_out, 0, _shrink(img_rect)))


@pytest.mark.integration
def test_full_page_rule_forces_strict_even_with_image_mode_none() -> None:
    """
    Option D: a full-page rule must wipe the page entirely, regardless of the
    user's image_mode. With image_mode='none' on a regular rect, images stay;
    with image_mode='none' but the rect sent in `full_page_rects`, the page
    is treated as strict (image removed, graphics removed).
    """
    pdf_in = _read_fixture("004_bitmap_image.pdf")
    before = _count_page_images(pdf_in, page_index=0)
    assert before > 0

    doc = pymupdf.open(stream=pdf_in, filetype="pdf")
    bounds = doc[0].rect
    doc.close()
    full_page = {
        "page": 0,
        "x0": bounds.x0,
        "y0": bounds.y0,
        "x1": bounds.x1,
        "y1": bounds.y1,
    }

    # Send the full-page rect via `full_page_rects`, with image_mode='none'.
    # Expected: image is removed because the page-rule forces strict mode.
    payload = {
        "rects": [],
        "full_page_rects": [full_page],
        "options": {"image_mode": "none", "apply_graphics": False},
        "audit": {
            "patterns": ["__NEVER_MATCH__"],
            "regex": False,
            "case_sensitive": True,
        },
    }
    resp = client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf_in, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )
    assert resp.status_code == 200, resp.text

    pdf_out = resp.content
    after = _count_page_images(pdf_out, page_index=0)
    assert after < before, "Full-page rule should force image removal."

    headers = resp.headers
    assert headers.get("X-Redaction-Full-Page-Occurrences") == "1"


@pytest.mark.integration
def test_full_page_via_rects_keeps_user_mode() -> None:
    """
    Sanity check: the same full-sized rect sent via `rects` (not `full_page_rects`)
    keeps the user's image_mode ('none' here), so the image stays.
    """
    pdf_in = _read_fixture("004_bitmap_image.pdf")
    before = _count_page_images(pdf_in, page_index=0)
    assert before > 0

    doc = pymupdf.open(stream=pdf_in, filetype="pdf")
    bounds = doc[0].rect
    doc.close()
    full_page = {
        "page": 0,
        "x0": bounds.x0,
        "y0": bounds.y0,
        "x1": bounds.x1,
        "y1": bounds.y1,
    }

    payload = {
        "rects": [full_page],
        "options": {"image_mode": "none", "apply_graphics": False},
        "audit": {
            "patterns": ["__NEVER_MATCH__"],
            "regex": False,
            "case_sensitive": True,
        },
    }
    resp = client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf_in, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )
    assert resp.status_code == 200, resp.text

    after = _count_page_images(resp.content, page_index=0)
    assert after == before, "image_mode='none' on a regular rect must keep the image."


@pytest.mark.integration
def test_image_mode_invalid_value_returns_422() -> None:
    """image_mode is a Literal; an unknown value must be rejected by the API."""
    pdf_in = _read_fixture("004_bitmap_image.pdf")
    payload = {
        "rects": [],
        "options": {"image_mode": "BOGUS", "apply_graphics": False},
        "audit": None,
    }
    resp = client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf_in, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )
    assert resp.status_code == 422


def _image_stream_pixels(pdf_bytes: bytes, page_index: int = 0) -> tuple[int, int]:
    """(pixels rouges, pixels totaux) du premier flux image embarqué.

    On inspecte le flux lui-même, pas le rendu de la page : en mode "none" un
    rectangle noir est dessiné par-dessus, si bien que la page paraît caviardée
    alors que les pixels d'origine sont toujours dans le fichier.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        images = doc[page_index].get_images(full=True)
        assert images, "Fixture expected to contain at least one image."
        pix = pymupdf.Pixmap(doc.extract_image(images[0][0])["image"])
        red = sum(
            1
            for y in range(pix.height)
            for x in range(pix.width)
            if pix.pixel(x, y)[0] > 150 and pix.pixel(x, y)[1] < 100 and pix.pixel(x, y)[2] < 100
        )
        return red, pix.width * pix.height
    finally:
        doc.close()


@pytest.mark.integration
def test_omitted_options_redact_image_pixels_by_default() -> None:
    """Un payload sans `options` doit caviarder les pixels, pas poser un calque.

    Le défaut serveur était `image_mode="none"` : l'appelant qui omettait
    `options` recevait un 200 et un PDF dont l'image d'origine restait entière
    sous un rectangle noir, récupérable en retirant le calque.
    """
    pdf_in = _read_fixture("004_bitmap_image.pdf")
    _, img_rect = _first_image_rect(pdf_in)

    red_before, total = _image_stream_pixels(pdf_in)
    assert red_before == total, "La fixture doit être un aplat rouge."

    inner = pymupdf.Rect(
        img_rect.x0 + img_rect.width * 0.2,
        img_rect.y0 + img_rect.height * 0.2,
        img_rect.x1 - img_rect.width * 0.2,
        img_rect.y1 - img_rect.height * 0.2,
    )
    payload = {
        "rects": [{"page": 0, "x0": inner.x0, "y0": inner.y0, "x1": inner.x1, "y1": inner.y1}]
    }

    resp = client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf_in, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )

    assert resp.status_code == 200, resp.text
    red_after, _ = _image_stream_pixels(resp.content)
    assert red_after < red_before, "Les pixels visés devaient être noircis dans le flux image."


@pytest.mark.integration
def test_unknown_option_key_is_rejected_not_ignored() -> None:
    """Une clé inconnue doit produire un 422 qui la nomme, jamais un 200 silencieux."""
    pdf_in = _read_fixture("004_bitmap_image.pdf")
    payload = {
        "rects": [],
        # Faute de frappe volontaire : camelCase au lieu de snake_case.
        "options": {"imageMode": "pixels"},
    }

    resp = client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf_in, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )

    assert resp.status_code == 422, resp.text
    assert "imageMode" in resp.text


@pytest.mark.integration
def test_unknown_top_level_key_is_rejected() -> None:
    """Le refus des clés inconnues vaut aussi au niveau du payload lui-même."""
    pdf_in = _read_fixture("004_bitmap_image.pdf")
    payload = {"rects": [], "sanitize_metdata": False}

    resp = client.post(
        "/redact/apply",
        files={
            "file": ("input.pdf", pdf_in, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )

    assert resp.status_code == 422, resp.text
    assert "sanitize_metdata" in resp.text
