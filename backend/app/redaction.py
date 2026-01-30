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


def redact_pdf_by_rectangles(pdf_bytes: bytes, rects: Iterable[RedactionRect]) -> bytes:
    """
    Applique des redactions à partir d'une liste de rectangles.

    Pour cette étape :
    - images OFF
    - vector graphics OFF
    - text removal ON (défaut)

    Retourne le PDF redigé (bytes).
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        by_page: dict[int, list[pymupdf.Rect]] = {}
        for r in rects:
            if r.page < 0 or r.page >= doc.page_count:
                raise ValueError(f"Invalid page index: {r.page} (page_count={doc.page_count})")

            rect = pymupdf.Rect(r.x0, r.y0, r.x1, r.y1)
            if rect.is_empty:
                raise ValueError(f"Empty rectangle: {rect}")

            # Normaliser au cas où (x0 > x1 / y0 > y1)
            rect = rect.normalize()
            by_page.setdefault(r.page, []).append(rect)

        # Ajouter annotations puis appliquer par page
        for page_no, rect_list in by_page.items():
            page = doc[page_no]
            for rect in rect_list:
                # Fill noir : standard "blackout".
                # (Le retrait réel du contenu est fait par apply_redactions.)
                page.add_redact_annot(rect, fill=(0, 0, 0))

            # IMPORTANT : désactiver explicitement images/vectors pour cette étape
            page.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_NONE,
                graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                # text = PDF_REDACT_TEXT_REMOVE est le défaut ; on le laisse tel quel.
            )

        out = BytesIO()
        # garbage élevé aide à purger les objets devenus inutiles après redaction.
        # :contentReference[oaicite:1]{index=1}
        doc.save(out, garbage=4, deflate=True)
        return out.getvalue()
    finally:
        doc.close()
