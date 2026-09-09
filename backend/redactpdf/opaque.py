"""Zones d'une page que les règles textuelles ne peuvent pas lire.

Pourquoi ce module existe
-------------------------
Mesuré le 9 septembre 2026, sur un PDF scanné sans couche texte : une règle
« Dupont » et le preset téléphone rendaient tous deux **HTTP 200**, image
intacte, donnée lisible à l'œil. C'est le mode d'échec que le projet déclare
impossible, atteint sans le moindre message.

Ce que le contrôle fait, et ce qu'il ne fait pas
-----------------------------------------------
Il est **purement géométrique**. Il ne regarde pas dans l'image et ne le prétend
pas : il ne distingue pas un tableau scanné d'une photo de chat. Il répond à une
seule question, « y a-t-il ici une zone que les règles n'ont pas pu lire », et
cette réponse reste vraie dans les deux cas. Une photo peut porter une plaque
d'immatriculation, un badge, un tableau blanc ; l'outil ne sait pas, et la seule
affirmation honnête est qu'il ne sait pas.

Conséquence assumée : une grande image décorative est signalée. Ce n'est pas un
faux positif, c'est une affirmation vraie que l'utilisateur trouvera pénible. Le
traitement est le carrousel d'acquittement, pas une heuristique plus fine.

Le cas hybride, qui a tué la première version
---------------------------------------------
Tester « la page a-t-elle du texte » ne détecte rien sur une page qui mêle un
en-tête en dur et un tableau scanné : la page a du texte, et la zone reste
invisible aux règles. D'où la mesure par image plutôt que par page.
"""
from __future__ import annotations

from dataclasses import dataclass

import pymupdf

# Une image sous ce seuil ne peut pas porter grand-chose. Mesuré : un logo occupe
# 0,3 % d'une A4, le bloc d'identité scanné de docs/demo-invoice.pdf en occupe
# 7,7 %. Le seuil est bas parce qu'un signalement de trop coûte une vignette à
# faire défiler, alors qu'un signalement manquant coûte une fuite.
MIN_PAGE_SHARE = 0.005

# Au-delà, l'image sert de fond à du vrai texte (filigrane, bandeau, trame) : les
# règles lisent ce qui est écrit dessus, l'image ne cache rien.
MAX_TEXT_RATIO = 0.05

# Une zone couverte à ce point par une règle géométrique est traitée : l'utilisateur
# a dessiné dessus, il n'y a plus rien à lui signaler.
MIN_COVER_RATIO = 0.95


@dataclass(frozen=True)
class OpaqueRegion:
    """Une zone que les règles textuelles n'ont pas pu lire."""

    page: int
    bbox: tuple[float, float, float, float]
    page_share: float
    text_ratio: float

    def as_dict(self) -> dict[str, object]:
        return {
            "page": self.page,
            "bbox": [round(v, 2) for v in self.bbox],
            "page_share": round(self.page_share, 4),
            "text_ratio": round(self.text_ratio, 4),
        }


def _regions_on_page(
    page: pymupdf.Page, page_number: int, *, min_share: float, max_text_ratio: float
) -> list[OpaqueRegion]:
    text_rects = [pymupdf.Rect(b[:4]) for b in page.get_text("blocks") if b[6] == 0]
    page_area = abs(page.rect)
    if page_area <= 0:
        return []

    out: list[OpaqueRegion] = []
    for info in page.get_image_info():
        rect = pymupdf.Rect(info["bbox"])
        area = abs(rect)
        if area <= 0:
            continue
        share = area / page_area
        if share < min_share:
            continue
        covered = sum(abs(rect & t) for t in text_rects) / area
        if covered > max_text_ratio:
            continue
        out.append(
            OpaqueRegion(
                page=page_number,
                bbox=(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)),
                page_share=share,
                text_ratio=covered,
            )
        )
    return out


def find_opaque_regions(
    pdf_bytes: bytes,
    *,
    pages: list[int] | None = None,
    min_share: float = MIN_PAGE_SHARE,
    max_text_ratio: float = MAX_TEXT_RATIO,
) -> list[OpaqueRegion]:
    """Zones opaques du document **d'origine**.

    Toujours l'original, jamais la sortie : la question posée est « qu'est-ce que
    les règles pouvaient lire au moment où elles ont travaillé », et une zone déjà
    caviardée n'y répondrait plus. Même invariant que pour les rectangles.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        if pages is None:
            wanted: list[int] = list(range(doc.page_count))
        else:
            wanted = [p for p in pages if 0 <= p < doc.page_count]
        out: list[OpaqueRegion] = []
        for index in wanted:
            out.extend(
                _regions_on_page(
                    doc.load_page(index),
                    index,
                    min_share=min_share,
                    max_text_ratio=max_text_ratio,
                )
            )
        return out
    finally:
        doc.close()


def drop_covered(
    regions: list[OpaqueRegion],
    covering: list[tuple[int, tuple[float, float, float, float]]],
    *,
    min_cover: float = MIN_COVER_RATIO,
) -> list[OpaqueRegion]:
    """Retire les zones qu'une règle géométrique traite déjà.

    C'est ce qui rend le contrôle vivable : le geste naturel devant un
    signalement, dessiner un rectangle, l'éteint définitivement pour cette zone.
    """
    remaining: list[OpaqueRegion] = []
    for region in regions:
        rect = pymupdf.Rect(region.bbox)
        area = abs(rect)
        if area <= 0:
            continue
        covered = sum(
            abs(rect & pymupdf.Rect(box)) for page, box in covering if page == region.page
        )
        if covered / area < min_cover:
            remaining.append(region)
    return remaining
