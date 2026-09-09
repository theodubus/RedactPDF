from __future__ import annotations

import pymupdf

# Porteurs situés hors du flux de contenu des pages. Le caviardage nettoie ce qui
# est dessiné ; ces objets-là transportent du texte que personne ne regarde et
# qu'aucune règle géométrique n'atteint. Mesuré avant d'écrire ceci : une règle
# « Dupont » nettoyait la page, rendait 200, et laissait le signet « Dossier
# Dupont - confidentiel » intact dans le volet de navigation.
#
# On supprime le porteur entier plutôt que d'y retrouver la cible. C'est plus
# brutal et plus sûr : on ne fuit pas par un objet qui n'existe plus, et cela
# n'oblige pas l'assainissement à connaître les règles.
_ACTION_KEYS = ("OpenAction", "AA")


def _drop_javascript_and_xfa(doc: pymupdf.Document) -> None:
    """Retire le JavaScript de document et le paquet XFA du catalogue."""
    try:
        catalog = doc.pdf_catalog()
    except Exception:
        return
    if not catalog:
        return

    for key in _ACTION_KEYS:
        try:
            kind, _ = doc.xref_get_key(catalog, key)
            if kind != "null":
                doc.xref_set_key(catalog, key, "null")
        except Exception:
            pass

    # /Names/JavaScript : arbre de noms des scripts de document.
    try:
        kind, _ = doc.xref_get_key(catalog, "Names/JavaScript")
        if kind != "null":
            doc.xref_set_key(catalog, "Names/JavaScript", "null")
    except Exception:
        pass

    # /AcroForm/XFA : le formulaire XML garde sa propre copie des valeurs saisies,
    # que la suppression des widgets ne touche pas.
    try:
        kind, _ = doc.xref_get_key(catalog, "AcroForm/XFA")
        if kind != "null":
            doc.xref_set_key(catalog, "AcroForm/XFA", "null")
    except Exception:
        pass


def sanitize_document(
    doc: pymupdf.Document,
    *,
    sanitize_metadata: bool = False,
    remove_annotations: bool = False,
    remove_attachments: bool = False,
    remove_outline: bool = False,
    remove_document_actions: bool = False,
) -> None:
    """
    Nettoyage 'anti-fuites hors visuel' sur un Document PyMuPDF déjà ouvert/modifié.
    À appeler juste avant doc.save(... garbage>0 ...).

    - sanitize_metadata: clear Info dict + XML metadata stream (XMP)
    - remove_annotations: supprime liens + annotations + widgets (form fields)
    - remove_attachments: supprime les embedded files
    - remove_outline: supprime les signets, dont les titres portent régulièrement
      un nom de dossier ou de personne
    - remove_document_actions: supprime le JavaScript de document, /OpenAction,
      /AA et le paquet XFA

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

    if remove_outline:
        try:
            doc.set_toc([])
        except Exception:
            pass

    if remove_document_actions:
        _drop_javascript_and_xfa(doc)

    if remove_attachments and hasattr(doc, "embfile_names") and hasattr(doc, "embfile_del"):
        try:
            names = list(doc.embfile_names())
        except Exception:
            names = []
        for name in names:
            doc.embfile_del(name)
