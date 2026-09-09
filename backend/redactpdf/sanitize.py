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


def _drain(node: object, delete: object) -> None:
    """Vide une chaîne d'annotations, sans se laisser arrêter par une poignée morte.

    `page.delete_annot(a)` rend l'entrée suivante de la chaîne, et c'est là que ça
    casse : sur un document réel (une convention de stage portant une annotation
    commentée), la suivante est le *popup* de celle qu'on vient de supprimer.
    Détaché de sa page avec son parent, il fait lever à PyMuPDF « Annot is not
    bound to a page », l'exception remonte et la requête entière rend 500. Une
    simple note collée suffit à déclencher ça, et le motif de boucle utilisé ici
    est pourtant celui de la documentation.

    On s'arrête donc à la première poignée cassée, et le filet ci-dessous finit le
    travail par référence. Ne jamais transformer ça en `continue` : la chaîne
    n'est plus fiable une fois qu'un maillon a lâché, et on tournerait en rond.
    """
    while node is not None:
        try:
            node = delete(node)  # type: ignore[operator]
        except Exception:
            return


def _drop_annot_references(doc: pymupdf.Document, page: pymupdf.Page) -> None:
    """Le filet : plus aucune annotation atteignable, quoi qu'ait fait la boucle.

    Couper la référence plutôt que supprimer objet par objet, dans l'esprit du
    module : on ne fuit pas par un objet que rien ne désigne, et `garbage=4` à
    l'enregistrement le fait disparaître physiquement.

    `/AcroForm/Fields` est coupé avec, car c'est le second chemin vers un widget :
    sa valeur saisie survivrait au vidage de `/Annots` si le formulaire la
    désignait encore. Retirer toutes les annotations d'un document, c'est retirer
    tous ses champs, donc le formulaire n'a plus de contenu à décrire.
    """
    try:
        if doc.xref_get_key(page.xref, "Annots")[0] != "null":
            doc.xref_set_key(page.xref, "Annots", "null")
    except Exception:
        pass

    try:
        catalog = doc.pdf_catalog()
        if catalog and doc.xref_get_key(catalog, "AcroForm/Fields")[0] != "null":
            doc.xref_set_key(catalog, "AcroForm/Fields", "null")
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
            _drain(annot, page.delete_annot)

            # 3) Widgets (form fields)
            widget = getattr(page, "first_widget", None)
            if widget is None:
                widget = getattr(page, "firstWidget", None)  # compat anciens noms
            _drain(widget, page.delete_widget)

            # 4) Le filet, toujours, pas seulement en cas d'échec : c'est lui qui
            # porte la garantie, la boucle n'étant qu'un chemin poli vers le même
            # résultat (elle tient la comptabilité du formulaire quand elle marche).
            _drop_annot_references(doc, page)

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
