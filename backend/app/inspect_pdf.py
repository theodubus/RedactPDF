from __future__ import annotations

from typing import Any

try:
    import pymupdf
except Exception:  # pragma: no cover
    import fitz as pymupdf  # type: ignore


def inspect_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    """
    Inspection "anti-fuite" : metadata, XML metadata, annotations/links/widgets, pièces jointes.
    Utile pour debugger vos tests et valider le sanitize.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        metadata = dict(doc.metadata or {})
        xml_xref = 0
        if hasattr(doc, "xml_metadata_xref"):
            try:
                xml_xref = int(doc.xml_metadata_xref())
            except Exception:
                xml_xref = 0

        attachments: list[str] = []
        if hasattr(doc, "embfile_names"):
            try:
                attachments = list(doc.embfile_names())
            except Exception:
                attachments = []

        pages = []
        total_links = 0
        total_annots = 0
        total_widgets = 0

        for pno in range(doc.page_count):
            page = doc.load_page(pno)

            # links
            try:
                links = page.get_links()
            except Exception:
                links = []
            total_links += len(links)

            # annots
            ann_count = 0
            annot = getattr(page, "first_annot", None)
            if annot is None:
                annot = getattr(page, "firstAnnot", None)
            while annot:
                ann_count += 1
                annot = annot.next  # type: ignore[attr-defined]
            total_annots += ann_count

            # widgets
            wid_count = 0
            widget = getattr(page, "first_widget", None)
            if widget is None:
                widget = getattr(page, "firstWidget", None)
            while widget:
                wid_count += 1
                widget = widget.next  # type: ignore[attr-defined]
            total_widgets += wid_count

            pages.append(
                {
                    "page": pno,
                    "links": len(links),
                    "annots": ann_count,
                    "widgets": wid_count,
                }
            )

        return {
            "metadata": metadata,
            "xml_metadata_xref": xml_xref,
            "embedded_files": attachments,
            "totals": {
                "links": total_links,
                "annots": total_annots,
                "widgets": total_widgets,
                "embedded_files": len(attachments),
            },
            "pages": pages,
        }
    finally:
        doc.close()
