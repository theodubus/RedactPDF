from __future__ import annotations

from dataclasses import dataclass

import pymupdf


@dataclass(frozen=True)
class SanitizeStats:
    metadata_cleared: bool
    xml_metadata_removed: bool
    links_removed: int
    annots_removed: int
    widgets_removed: int
    attachments_removed: int


def sanitize_document(
    doc: pymupdf.Document,
    *,
    sanitize_metadata: bool = False,
    remove_annotations: bool = False,
    remove_attachments: bool = False,
) -> SanitizeStats:
    """
    Nettoyage 'anti-fuites hors visuel' sur un Document PyMuPDF déjà ouvert/modifié.
    À appeler juste avant doc.save(... garbage>0 ...).

    - sanitize_metadata: clear Info dict + XML metadata stream (XMP)
    - remove_annotations: supprime liens + annotations + widgets (form fields)
    - remove_attachments: supprime les embedded files
    """
    metadata_cleared = False
    xml_metadata_removed = False
    links_removed = 0
    annots_removed = 0
    widgets_removed = 0
    attachments_removed = 0

    if sanitize_metadata:
        # Doc PyMuPDF: doc.set_metadata({}) + doc.del_xml_metadata()
        # IMPORTANT: la suppression physique nécessite un save avec garbage > 0.
        doc.set_metadata({})
        metadata_cleared = True

        # PDF uniquement – si absent, PyMuPDF lèvera potentiellement une exception selon versions
        if hasattr(doc, "del_xml_metadata"):
            try:
                doc.del_xml_metadata()
                xml_metadata_removed = True
            except Exception:
                # si pas de XML metadata, certaines versions peuvent lever – ce n'est pas bloquant
                xml_metadata_removed = False

    if remove_annotations:
        for pno in range(doc.page_count):
            page = doc.load_page(pno)

            # 1) Liens (link annotations) via get_links / delete_link
            try:
                links = page.get_links()
            except Exception:
                links = []
            for link in links:
                page.delete_link(link)
                links_removed += 1

            # 2) Annotations (hors widgets)
            annot = getattr(page, "first_annot", None)
            if annot is None:
                annot = getattr(page, "firstAnnot", None)  # compat anciens noms

            while annot:
                annots_removed += 1
                annot = page.delete_annot(annot)

            # 3) Widgets (form fields)
            widget = getattr(page, "first_widget", None)
            if widget is None:
                widget = getattr(page, "firstWidget", None)  # compat anciens noms

            while widget:
                widgets_removed += 1
                widget = page.delete_widget(widget)

    if remove_attachments and hasattr(doc, "embfile_names") and hasattr(doc, "embfile_del"):
        try:
            names = list(doc.embfile_names())
        except Exception:
            names = []
        for name in names:
            doc.embfile_del(name)
            attachments_removed += 1

    return SanitizeStats(
        metadata_cleared=metadata_cleared,
        xml_metadata_removed=xml_metadata_removed,
        links_removed=links_removed,
        annots_removed=annots_removed,
        widgets_removed=widgets_removed,
        attachments_removed=attachments_removed,
    )
