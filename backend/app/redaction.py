from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO

import pymupdf


@dataclass(frozen=True)
class RedactionRect:
    """Rectangle de redaction en coordonnées PyMuPDF (points), page indexée à partir de 0."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


def redact_pdf_by_rectangles(
    pdf_bytes: bytes,
    rects: Iterable[RedactionRect],
    *,
    apply_images: bool = False,
    apply_graphics: bool = False,
) -> bytes:
    """
    Applique des redactions à partir d'une liste de rectangles.

    Par défaut, ce comportement reste conservateur :
    - images OFF
    - vector graphics OFF
    - text removal ON

    Si activé :
    - apply_images=True  -> suppression des images chevauchant les zones redigées
    - apply_graphics=True -> suppression des dessins vectoriels chevauchant les zones redigées

    Retourne le PDF redigé (bytes).
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        by_page: dict[int, list[pymupdf.Rect]] = {}
        for r in rects:
            if r.page < 0 or r.page >= doc.page_count:
                raise ValueError(f"Invalid page index: {r.page} (page_count={doc.page_count})")

            rect = pymupdf.Rect(r.x0, r.y0, r.x1, r.y1).normalize()
            if rect.is_empty:
                raise ValueError(f"Empty rectangle: {rect}")

            by_page.setdefault(r.page, []).append(rect)

        images_mode = (
            pymupdf.PDF_REDACT_IMAGE_REMOVE if apply_images else pymupdf.PDF_REDACT_IMAGE_NONE
        )
        graphics_mode = (
            pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED
            if apply_graphics
            else pymupdf.PDF_REDACT_LINE_ART_NONE
        )

        # Ajouter annotations puis appliquer par page
        for page_no, rect_list in by_page.items():
            page = doc[page_no]
            for rect in rect_list:
                # Fill noir : standard "blackout".
                # (Le retrait réel du contenu est fait par apply_redactions.)
                page.add_redact_annot(rect, fill=(0, 0, 0))

            page.apply_redactions(
                images=images_mode,
                graphics=graphics_mode,
                # text = PDF_REDACT_TEXT_REMOVE est le défaut ; on le laisse tel quel.
            )

        out = BytesIO()
        # garbage élevé aide à purger les objets devenus inutiles après redaction.
        doc.save(out, garbage=4, deflate=True)
        return out.getvalue()
    finally:
        doc.close()
