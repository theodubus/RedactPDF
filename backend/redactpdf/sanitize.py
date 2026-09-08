from __future__ import annotations

import pymupdf


def sanitize_document(
    doc: pymupdf.Document,
    *,
    sanitize_metadata: bool = False,
    remove_annotations: bool = False,
    remove_attachments: bool = False,
) -> None:
    """
    Nettoyage 'anti-fuites hors visuel' sur un Document PyMuPDF déjà ouvert/modifié.
    À appeler juste avant doc.save(... garbage>0 ...).

    - sanitize_metadata: clear Info dict + XML metadata stream (XMP)
    - remove_annotations: supprime liens + annotations + widgets (form fields)
    - remove_attachments: supprime les embedded files

    Ne renvoie pas de compteurs : ils n'étaient lus nulle part, et les tests de
    sanitation vérifient le PDF de sortie -- ce qui est plus fort que de croire
    un compteur sur parole.
    """
    if sanitize_metadata:
        # Doc PyMuPDF: doc.set_metadata({}) + doc.del_xml_metadata()
        # IMPORTANT: la suppression physique nécessite un save avec garbage > 0.
        doc.set_metadata({})

        # PDF uniquement – si absent, PyMuPDF lèvera potentiellement une exception selon versions
        if hasattr(doc, "del_xml_metadata"):
            try:
                doc.del_xml_metadata()
            except Exception:
                # si pas de XML metadata, certaines versions peuvent lever – ce n'est pas bloquant
                pass

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

            # 2) Annotations (hors widgets)
            annot = getattr(page, "first_annot", None)
            if annot is None:
                annot = getattr(page, "firstAnnot", None)  # compat anciens noms

            while annot:
                annot = page.delete_annot(annot)

            # 3) Widgets (form fields)
            widget = getattr(page, "first_widget", None)
            if widget is None:
                widget = getattr(page, "firstWidget", None)  # compat anciens noms

            while widget:
                widget = page.delete_widget(widget)

    if remove_attachments and hasattr(doc, "embfile_names") and hasattr(doc, "embfile_del"):
        try:
            names = list(doc.embfile_names())
        except Exception:
            names = []
        for name in names:
            doc.embfile_del(name)
