from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO

import pymupdf

from redactpdf.sanitize import sanitize_document


@dataclass(frozen=True)
class RedactionRect:
    """Rectangle de redaction en coordonnées PyMuPDF (points), page indexée à partir de 0."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float

    # Vrai seulement quand le rectangle vient d'un texte écrit horizontalement.
    # Seuls ces rectangles-là sont resserrés verticalement : pour un texte pivoté
    # la hauteur EST la direction de lecture, et la resserrer coupe le début et la
    # fin du mot. Le défaut est `False` : un producteur qui ne se prononce pas
    # obtient un rectangle intact, c'est-à-dire qui caviarde plutôt plus que
    # moins. Les rectangles tracés à la main gardent ce défaut — une intention
    # explicite ne doit pas être modifiée en silence.
    from_horizontal_text: bool = False


def _tighten_rect_vertical(rect: pymupdf.Rect) -> pymupdf.Rect:
    """
    Rétrécit agressivement un rectangle en hauteur pour éviter d'impacter la ligne du dessous.

    Idée:
    - Les rectangles issus d'extraction peuvent inclure une "line box" trop haute.
    - On conserve le centre vertical et on limite la hauteur à une fraction de la hauteur initiale.

    Politique:
    - target_height = clamp(h * 0.60, min=3.0 pt, max=12.0 pt)
    - recentrage vertical sur le milieu du rect
    - si ça devient dégénéré, on retombe sur un inset simple
    """
    h = float(rect.y1 - rect.y0)
    if h <= 0:
        return rect

    # Les zones volumineuses (ex: page complète) ne doivent pas être compressées verticalement.
    if h > 24.0:
        return rect

    target = h * 0.60
    if target < 3.0:
        target = 3.0
    if target > 12.0:
        target = 12.0

    if target >= h:
        # Rien à faire : trop petit ou déjà serré
        return rect

    cy = (float(rect.y0) + float(rect.y1)) / 2.0
    y0 = cy - target / 2.0
    y1 = cy + target / 2.0
    if y1 <= y0:
        return rect

    tightened = pymupdf.Rect(rect.x0, y0, rect.x1, y1)

    # Filet de sécurité : si jamais on a trop resserré sur des polices à grande hauteur,
    # on applique un petit inset au lieu de casser.
    if tightened.is_empty:
        return rect

    return tightened



# Annoté explicitement : PyMuPDF ne publie pas de types, donc ces constantes
# arrivent en `Any`. L'annotation dit ce qu'on attend d'elles, et un bump de
# pymupdf qui changerait leur nature deviendrait une erreur de vérification
# plutôt qu'un comportement silencieusement différent.
_IMAGE_MODE_MAP: dict[str, int] = {
    "none": pymupdf.PDF_REDACT_IMAGE_NONE,
    "remove": pymupdf.PDF_REDACT_IMAGE_REMOVE,
    "pixels": pymupdf.PDF_REDACT_IMAGE_PIXELS,
}


def _resolve_image_mode(mode: str) -> int:
    try:
        return _IMAGE_MODE_MAP[mode]
    except KeyError as e:
        allowed = ", ".join(sorted(_IMAGE_MODE_MAP))
        raise ValueError(f"Invalid image_mode {mode!r}. Allowed: {allowed}.") from e


def redact_pdf_by_rectangles(
    pdf_bytes: bytes,
    rects: Iterable[RedactionRect],
    *,
    image_mode: str = "none",
    apply_graphics: bool = False,
    sanitize_metadata: bool = False,
    remove_annotations: bool = False,
    remove_attachments: bool = False,
    remove_outline: bool = False,
    remove_document_actions: bool = False,
) -> bytes:
    """
    Applique des redactions à partir d'une liste de rectangles.

    Modes images :
    - "none"    -> ne touche pas aux images (défaut)
    - "remove"  -> retire intégralement les images intersectées par un rect
    - "pixels"  -> noircit uniquement les pixels intersectés (caviardage partiel)

    Autres options :
    - apply_graphics=True      -> suppression des dessins vectoriels touchés
    - sanitize_metadata=True   -> nettoyage métadonnées (Info dict + XMP si possible)
    - remove_annotations=True  -> suppression des annotations/liens/widgets
    - remove_attachments=True  -> suppression des fichiers embarqués
    - remove_outline=True      -> suppression des signets
    - remove_document_actions=True -> suppression du JavaScript, /OpenAction,
      /AA et du paquet XFA

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

            if r.from_horizontal_text:
                rect = _tighten_rect_vertical(rect)

            by_page.setdefault(r.page, []).append(rect)

        images_mode = _resolve_image_mode(image_mode)
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

        # Nettoyage "anti-fuite hors visuel" juste avant l'export.
        # IMPORTANT : la suppression physique est finalisée par doc.save(... garbage>0 ...).
        sanitize_document(
            doc,
            sanitize_metadata=sanitize_metadata,
            remove_annotations=remove_annotations,
            remove_attachments=remove_attachments,
            remove_outline=remove_outline,
            remove_document_actions=remove_document_actions,
        )

        out = BytesIO()
        # garbage élevé aide à purger les objets devenus inutiles après redaction + sanitation.
        doc.save(out, garbage=4, deflate=True)
        return out.getvalue()
    finally:
        doc.close()
