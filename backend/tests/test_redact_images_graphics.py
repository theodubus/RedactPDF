from __future__ import annotations

import json
from pathlib import Path

import pymupdf  # PyMuPDF
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.redaction import RedactionRect, redact_pdf_by_rectangles

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
    apply_images: bool,
    apply_graphics: bool
):
    payload = {
        "rects": [
            {"page": r.page, "x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1}
            for r in rects
        ],
        "options": {
            "apply_images": apply_images,
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

    # Control: images disabled -> should not reduce referenced images
    pdf_keep = redact_pdf_by_rectangles(
        pdf_in,
        [rect],
        apply_images=False,
        apply_graphics=False,
    )
    after_keep = _count_page_images(pdf_keep, page_index=0)
    assert after_keep == before

    # Now enable image removal -> referenced images should decrease
    pdf_removed = redact_pdf_by_rectangles(
        pdf_in,
        [rect],
        apply_images=True,
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
        apply_images=False,
        apply_graphics=False,
    )
    after_keep = _count_drawings(pdf_keep, page_index=0)
    assert after_keep >= before  # peut augmenter (blackout)

    # Enable graphics removal -> should reduce drawings
    pdf_removed = redact_pdf_by_rectangles(
        pdf_in,
        [rect],
        apply_images=False,
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

    # Control: apply_images=False
    resp_keep = _post_redact_rectangles(pdf_in, [rect], apply_images=False, apply_graphics=False)
    assert resp_keep.status_code == 200
    pdf_keep = resp_keep.content
    assert _count_page_images(pdf_keep, page_index=0) == before

    # Now enable apply_images=True
    resp_removed = _post_redact_rectangles(pdf_in, [rect], apply_images=True, apply_graphics=False)
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
    resp_keep = _post_redact_rectangles(pdf_in, [rect], apply_images=False, apply_graphics=False)
    assert resp_keep.status_code == 200
    pdf_keep = resp_keep.content
    after_keep = _count_drawings(pdf_keep, page_index=0)
    assert after_keep >= before  # peut augmenter (blackout)

    # Now enable apply_graphics=True
    resp_removed = _post_redact_rectangles(pdf_in, [rect], apply_images=False, apply_graphics=True)
    assert resp_removed.status_code == 200
    pdf_removed = resp_removed.content
    after_removed = _count_drawings(pdf_removed, page_index=0)
    assert after_removed < after_keep
