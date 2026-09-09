"""Proposer des zones dans les images, sans jamais rien garantir.

Ce module est le seul du paquet dont la sortie n'est **pas** couverte par le
contrat. Tout le reste répond « ce que le moteur déterministe a su lire, il l'a
retiré ». L'OCR, lui, est un détecteur approximatif : il lit parfois mal, il rate
parfois tout, et rien dans la sortie ne permet de savoir lequel des deux vient de
se produire. Il ne peut donc pas entrer dans la garantie, et il n'y entre pas.

Ce qu'il fait
-------------
Il donne une couche texte aux zones que les règles n'ont pas pu lire, puis y
lance **les mêmes règles**, sans en réécrire une seule. C'est le point de
conception qui compte : un second moteur d'appariement dériverait du premier, et
« caviarde `Dupont` » ne voudrait plus dire la même chose selon que le nom est
dans le texte ou dans une image. Les rectangles obtenus reviennent au repère de
la page par l'inverse de la matrice de placement, celle-là même qui sert déjà à
situer les zones déjà couvertes.

Ce qu'il ne fait pas
--------------------
Une proposition n'éteint jamais un signalement. Elle ne nourrit pas
`drop_covered`, et c'est une invariante, pas un détail d'implémentation : sinon
un détecteur approximatif suffirait à faire disparaître l'écran de revue, et la
validation humaine que le mode `review` existe pour imposer sauterait toute
seule. `block` n'est pas déverrouillé non plus : une zone parcourue par un
détecteur approximatif n'est pas une zone lue.

L'audit ne change pas davantage. Il relit le texte de la sortie ; ce qu'un OCR a
trouvé dans une image n'y a jamais été, donc il ne peut ni le confirmer ni
l'infirmer. Le rapport le dit.

Empaquetage
-----------
Tesseract est une dépendance native de l'ordre de 22 Mo, mesurée le 9 septembre
2026 (16 Mo de données de langue, 3,1 Mo de bibliothèque, 2,6 Mo de leptonica).
Le binaire figé vend « un fichier, rien à installer » : l'embarquer contredirait
cette promesse pour une fonction qui ne porte aucune garantie. On détecte donc un
tesseract système et on se désactive proprement s'il est absent.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pymupdf

from redactpdf.opaque import OpaqueRegion
from redactpdf.presets import find_redaction_rectangles_for_presets
from redactpdf.redaction import RedactionRect
from redactpdf.regex_guard import RegexBudget
from redactpdf.search import SearchOptions, find_redaction_rectangles

# Langue par défaut : le projet est francophone et sa région téléphone par défaut
# l'est aussi. Retombe sur l'anglais si le français n'est pas installé, plutôt que
# d'échouer sur une langue absente.
DEFAULT_LANGUAGE = "fra"
FALLBACK_LANGUAGE = "eng"


@dataclass(frozen=True)
class OcrProposal:
    """Un rectangle proposé par l'OCR, en coordonnées de page.

    `text` et `rule` existent pour le rapport : l'utilisateur doit pouvoir lire
    ce que le détecteur a cru voir et quelle règle s'y est appliquée, sinon la
    proposition est une boîte noire qui demande d'être crue sur parole.
    """

    page: int
    bbox: tuple[float, float, float, float]
    rule: str

    def as_dict(self) -> dict[str, object]:
        return {
            "page": self.page,
            "bbox": [round(v, 2) for v in self.bbox],
            "rule": self.rule,
        }

    def as_rect(self) -> RedactionRect:
        return RedactionRect(
            page=self.page,
            x0=self.bbox[0],
            y0=self.bbox[1],
            x1=self.bbox[2],
            y1=self.bbox[3],
        )


def available_languages() -> list[str]:
    """Les langues qu'un tesseract système propose, vide s'il n'y en a pas."""
    try:
        tessdata = pymupdf.get_tessdata()
    except Exception:
        return []
    if not tessdata:
        return []
    import pathlib

    try:
        return sorted(p.stem for p in pathlib.Path(str(tessdata)).glob("*.traineddata"))
    except Exception:
        return []


def is_available() -> bool:
    """Vrai si un tesseract exploitable est installé sur la machine.

    Appelé aussi par `/api/config`, pour que l'interface puisse griser la case
    plutôt que de proposer une fonction qui échouerait à l'export.
    """
    return bool(available_languages())


def resolve_language(requested: str | None) -> str | None:
    """La langue à utiliser, ou None si aucune n'est utilisable."""
    langs = available_languages()
    if not langs:
        return None
    for candidate in (requested, DEFAULT_LANGUAGE, FALLBACK_LANGUAGE):
        if candidate and candidate in langs:
            return candidate
    return langs[0]


def _page_from_unit(
    transform: tuple[float, float, float, float, float, float], x: float, y: float
) -> tuple[float, float]:
    a, b, c, d, e, f = transform
    return (a * x + c * y + e, b * x + d * y + f)


def _to_page_rect(
    region: OpaqueRegion, rect: RedactionRect, width: float, height: float
) -> tuple[float, float, float, float]:
    """Un rectangle du mini-PDF ramené sur la page qui porte l'image.

    Passe par la matrice de placement complète, et prend l'enveloppe des quatre
    coins : sur une image posée tournée, la boîte alignée aux axes du mini-PDF
    ne l'est plus une fois sur la page.
    """
    corners = [
        _page_from_unit(region.transform, x / width, y / height)
        for x, y in (
            (rect.x0, rect.y0),
            (rect.x1, rect.y0),
            (rect.x0, rect.y1),
            (rect.x1, rect.y1),
        )
    ]
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _ocr_region(doc: pymupdf.Document, region: OpaqueRegion, language: str) -> bytes | None:
    """Les pixels de la zone, rendus en mini-PDF porteur d'une couche texte OCR.

    Un vrai PDF, et pas une liste de mots, parce que c'est ce qui permet de lui
    appliquer les règles existantes telles quelles.
    """
    if not region.xref:
        # Image en ligne ou apparence d'annotation : pas d'objet à extraire. On
        # ne rend pas la région à la place, ce qui ferait passer du texte de page
        # pour du texte d'image et donnerait une proposition sur du déjà lu.
        return None
    try:
        pix = pymupdf.Pixmap(doc, region.xref)
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        # `bytes(...)` n'est pas décoratif, et `pix` doit rester vivant jusque-là :
        # le tampon rendu est adossé au Pixmap, et le laisser mourir dans
        # l'expression rend un PDF tronqué. Mesuré : 124 caractères lus au lieu
        # de 342, sans la moindre erreur levée.
        return bytes(pix.pdfocr_tobytes(language=language))
    except Exception:
        return None


def propose_from_regions(
    pdf_bytes: bytes,
    regions: Sequence[OpaqueRegion],
    *,
    searches: Sequence[SearchOptions] = (),
    regex_patterns: Sequence[tuple[list[str], bool, bool, bool]] = (),
    presets: Sequence[str] = (),
    language: str | None = None,
    budget: RegexBudget | None = None,
) -> list[OcrProposal]:
    """Les zones que les règles trouvent **dans la couche OCR** des images.

    Aucune règle n'est réécrite ici : le mini-PDF produit par l'OCR est un PDF
    comme un autre, et il passe par les mêmes fonctions que le document. C'est ce
    qui garantit que « caviarder Dupont » veut dire la même chose des deux côtés.
    """
    from redactpdf.multiline_regex_engine import find_redaction_rectangles_by_regex

    lang = resolve_language(language)
    if lang is None or not regions:
        return []
    if not (searches or regex_patterns or presets):
        return []

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    out: list[OcrProposal] = []
    try:
        for region in regions:
            mini_bytes = _ocr_region(doc, region, lang)
            if not mini_bytes:
                continue
            mini = pymupdf.open(stream=mini_bytes, filetype="pdf")
            try:
                if mini.page_count == 0:
                    continue
                box = mini.load_page(0).rect
                width, height = float(box.width), float(box.height)
                if width <= 0 or height <= 0:
                    continue

                found: list[tuple[str, RedactionRect]] = []
                for opts in searches:
                    label = f"search:{opts.query}"
                    for rect in find_redaction_rectangles(mini_bytes, opts, budget=budget):
                        found.append((label, rect))
                for patterns, case_sensitive, multiline, ignore_accents in regex_patterns:
                    label = f"regex:{patterns[0] if patterns else ''}"
                    for rect in find_redaction_rectangles_by_regex(
                        mini_bytes,
                        patterns,
                        case_sensitive=case_sensitive,
                        multiline=multiline,
                        ignore_accents=ignore_accents,
                        budget=budget,
                    ):
                        found.append((label, rect))
                if presets:
                    for rect in find_redaction_rectangles_for_presets(
                        mini_bytes, list(presets), budget=budget
                    ):
                        found.append(("preset", rect))

                for label, rect in found:
                    out.append(
                        OcrProposal(
                            page=region.page,
                            bbox=_to_page_rect(region, rect, width, height),
                            rule=label,
                        )
                    )
            finally:
                mini.close()
        return out
    finally:
        doc.close()
