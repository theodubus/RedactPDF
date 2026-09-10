"""Ce que les règles textuelles n'ont pas pu lire.

Deux mécanismes différents, un seul mode d'échec. Une **zone opaque** est une
image sans texte par-dessus ; une **police non fiable** est une police dont
l'extraction ne rend pas de l'Unicode exploitable. Dans les deux cas la règle ne
trouve rien, l'audit ne trouve rien non plus, et l'export réussissait en silence.

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

Le cas hybride, qui a tué deux versions
---------------------------------------
Tester « la page a-t-elle du texte » ne détecte rien sur une page qui mêle un
en-tête en dur et un tableau scanné : la page a du texte, et la zone reste
invisible aux règles. D'où la mesure par image plutôt que par page.

La deuxième version a refait la même faute d'un cran plus bas. Elle écartait une
image dont plus de 5 % de la surface passait sous un bloc de texte, au motif
qu'une image sous du texte est un fond. Mesuré le 9 septembre 2026 sur un relevé
de notes réel : un scan pleine page (93,7 % de la page) portant tout le
formulaire en pixels, surmonté de neuf blocs de texte épars qui en couvraient
18,6 %. Écarté, donc. Une règle sur le nom de l'établissement, écrit dans
l'image, rendait HTTP 200 sans rien caviarder.

Un ratio de surface ignore la forme, exactement comme le seuil de couverture à
95 % écarté plus bas. 18,6 % de couverture ne dit pas que les règles ont lu
l'image, seulement que 18,6 % de sa surface se trouve sous une ligne de texte.
Les 81,4 % restants n'ont été lus par personne. Le critère a donc disparu : une
image assez grande est signalée, qu'il y ait du texte par-dessus ou non. Un
filigrane sous une page de texte est signalé lui aussi, et c'est correct : il
porte un mot que rien ne peut lire.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

import pymupdf

# Plancher sous lequel une image n'est pas examinée. **Troisième valeur de ce
# seuil, et les deux premières étaient fausses de la même façon.**
#
# Il a valu 0,5 % de la page, sur l'idée qu'« une image sous ce seuil ne peut pas
# porter grand-chose ». Mesuré le 10 septembre 2026, c'était faux : un tampon de
# 60 x 39 points sur une A4, soit 0,467 %, portant le nom BOURDILLON en 250 x 163
# pixels, donne HTTP 200, audit `pass`, zéro occurrence, aucune revue, et le nom
# se relit parfaitement dans l'image de sortie (l'OCR le rend mot pour mot).
# C'est exactement la famille d'échec que le contrôle existe pour fermer :
# « je n'aurais pas pu le voir, mais je conclus succès ».
#
# Une part de surface ignore la forme. C'est le troisième seuil de cette famille
# à tomber pour cette raison, après la couverture à 95 % et le `text_ratio` à
# 5 %, et il tombe de la même manière : on ne garde pas un critère de surface
# pour décider si quelque chose a été lu.
#
# Le plancher restant vaut celui de l'OCR, et les deux constantes ne font plus
# qu'une : la question « peut-on lire quelque chose dedans » et la question
# « faut-il le signaler » ont désormais la même réponse. Le projet avait déjà
# tranché que 0,02 % vaut la peine d'être lu ; il n'y a pas de raison que ce qui
# vaut la peine d'être lu ne vaille pas la peine d'être dit.
#
# Coût mesuré sur 17 documents réels (bulletins, convention de stage, corpus de
# test Stirling) : **6 zones de plus au total**, sur 3 documents. Le pire cas
# existe et a été construit, 40 icônes *distinctes* à 0,065 % donnent 40 écrans ;
# 40 icônes identiques n'en donnent qu'un, puisque le regroupement se fait par
# empreinte de pixels. Aucun document du corpus réel n'a la moindre image sous
# 0,02 %. Le sur-signalement reste le bon sens de l'erreur : il coûte une
# vignette à faire défiler ou un mode `ignore` assumé, là où le sous-signalement
# coûte une fuite silencieuse.
MIN_PAGE_SHARE = 0.0002

# Marge tolérée sur chaque bord quand on juge qu'un rectangle couvre une zone.
# Deux points : de quoi absorber un tracé à la main imprécis, pas de quoi laisser
# passer un caractère, qui fait environ 5 x 9 points en corps 9.
#
# Ce seuil a d'abord été un ratio de surface, à 95 %. C'était faux : la surface
# ignore la forme. Mesuré sur le bloc d'identité de docs/demo-invoice.pdf, une
# bande non couverte de 16 x 120 points, soit trois caractères de large sur toute
# la hauteur, restait sous les 5 % et éteignait le signalement en silence.
COVER_TOLERANCE_PT = 2.0


@dataclass(frozen=True)
class OpaqueRegion:
    """Une zone que les règles textuelles n'ont pas pu lire.

    `digest` est l'empreinte des pixels, rendue par PyMuPDF. Deux zones qui la
    partagent sont la même image : un bandeau d'en-tête répété sur trente pages
    donne trente zones et une seule empreinte. C'est ce qui permet de ne la faire
    regarder qu'une fois sans mentir, puisque ce sont littéralement les mêmes
    pixels.
    """

    page: int
    bbox: tuple[float, float, float, float]
    page_share: float
    text_ratio: float
    digest: str
    xref: int
    # Matrice qui place le carré unité sur la page. Son inverse ramène un point de
    # la page dans le repère de l'image, ce qui est le seul moyen correct de
    # situer un rectangle sur une image tournée ou retournée.
    transform: tuple[float, float, float, float, float, float]

    def as_dict(self) -> dict[str, object]:
        return {
            "page": self.page,
            "bbox": [round(v, 2) for v in self.bbox],
            "page_share": round(self.page_share, 4),
            "text_ratio": round(self.text_ratio, 4),
            "digest": self.digest,
        }


def _regions_on_page(
    page: pymupdf.Page, page_number: int, *, min_share: float
) -> list[OpaqueRegion]:
    text_rects = [pymupdf.Rect(b[:4]) for b in page.get_text("blocks") if b[6] == 0]
    page_area = abs(page.rect)
    if page_area <= 0:
        return []

    out: list[OpaqueRegion] = []
    # `hashes=True` : sans lui PyMuPDF ne calcule pas l'empreinte des pixels.
    for info in page.get_image_info(hashes=True, xrefs=True):
        rect = pymupdf.Rect(info["bbox"])
        area = abs(rect)
        if area <= 0:
            continue
        share = area / page_area
        if share < min_share:
            continue
        # `text_ratio` est reporté, pas filtré. Il dit à l'utilisateur combien de
        # la zone se trouve sous du texte déjà lisible ; il ne dit pas que les
        # règles ont lu l'image, et une version antérieure qui s'en servait comme
        # critère écartait un scan pleine page pour 18,6 % de recouvrement.
        covered = sum(abs(rect & t) for t in text_rects) / area
        digest = info.get("digest")
        matrix = tuple(float(v) for v in info.get("transform", (1.0, 0, 0, 1.0, 0, 0)))
        out.append(
            OpaqueRegion(
                page=page_number,
                bbox=(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)),
                page_share=share,
                text_ratio=covered,
                digest=digest.hex() if isinstance(digest, bytes) else str(digest or ""),
                xref=int(info.get("xref", 0)),
                transform=(matrix + (0.0,) * 6)[:6],  # type: ignore[arg-type]
            )
        )
    return out


def find_opaque_regions(
    pdf_bytes: bytes,
    *,
    pages: list[int] | None = None,
    min_share: float = MIN_PAGE_SHARE,
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
                _regions_on_page(doc.load_page(index), index, min_share=min_share)
            )
        return out
    finally:
        doc.close()


def drop_covered(
    regions: list[OpaqueRegion],
    covering: list[tuple[int, tuple[float, float, float, float]]],
    *,
    tolerance: float = COVER_TOLERANCE_PT,
) -> list[OpaqueRegion]:
    """Retire les zones qu'un rectangle recouvre **entièrement**.

    C'est ce qui rend le contrôle vivable : le geste naturel devant un
    signalement, dessiner un rectangle, l'éteint définitivement pour cette zone.

    On exige qu'un **seul** rectangle contienne la zone, à la tolérance près,
    plutôt qu'une somme de surfaces. Deux rectangles qui se partagent une zone ne
    l'éteignent donc pas, et c'est volontaire : rien ne garantit qu'ils se
    touchent, et l'interstice est précisément là où un caractère survit. Le coût
    est un signalement de trop, que l'utilisateur lève en agrandissant son
    rectangle ou en l'acquittant.
    """
    remaining: list[OpaqueRegion] = []
    for region in regions:
        x0, y0, x1, y1 = region.bbox
        core = pymupdf.Rect(
            x0 + tolerance, y0 + tolerance, x1 - tolerance, y1 - tolerance
        )
        if core.is_empty:  # zone plus petite que la tolérance : rien à protéger
            continue

        covered = any(
            page == region.page and _contains(pymupdf.Rect(box), core)
            for page, box in covering
        )
        if not covered:
            remaining.append(region)
    return remaining


def _contains(outer: pymupdf.Rect, inner: pymupdf.Rect) -> bool:
    return bool(
        inner.x0 >= outer.x0
        and inner.y0 >= outer.y0
        and inner.x1 <= outer.x1
        and inner.y1 <= outer.y1
    )


# --------------------------------------------------------------------------
# Polices dont l'extraction ne rend pas de l'Unicode exploitable
#
# Mesuré : la même police TrueType intégrée en /Identity-H rend
#   avec /ToUnicode  ->  'Jean Dupont 06 12 34 56 78'
#   sans /ToUnicode  ->  'ðĊĆēÆêĚĕĔēęÆÖÜÆ×ØÆÙÚÆÛÜÆÝÞ'
# La règle ne trouve rien, l'audit non plus, et l'export partait en 200.
#
# Le critère n'est pas « composite sans /ToUnicode ». Une première version l'a
# cru et se serait déclenchée sur tout document CJK : les polices intégrées de
# PyMuPDF utilisent /UniGB-UTF16-H, une CMap de registre publiquement définie qui
# donne l'Unicode à elle seule, et s'extraient parfaitement sans /ToUnicode.
#
# Ce qui rend une police illisible, c'est un encodage sans sens Unicode :
#   /Identity-H et /Identity-V  le code EST l'indice de glyphe dans la police,
#                               il ne veut rien dire hors d'elle
#   Type3                       les glyphes sont des procédures de dessin
# Dans ces cas /ToUnicode est la seule table de correspondance, et son absence
# rend le texte inexploitable pour l'appariement comme pour l'audit.
#
# Une Type1 ou TrueType simple à encodage standard s'extrait correctement sans
# /ToUnicode : Helvetica en est la preuve.
# --------------------------------------------------------------------------

# Encodages qui ne portent aucune information Unicode par eux-mêmes.
_OPAQUE_ENCODING_PREFIX = "Identity"


@dataclass(frozen=True)
class UnreliableFont:
    """Une police d'une page dont on ne sait pas lire le texte."""

    page: int
    name: str
    subtype: str

    def as_dict(self) -> dict[str, object]:
        return {"page": self.page, "name": self.name, "subtype": self.subtype}


def find_unreliable_fonts(
    pdf_bytes: bytes, *, pages: list[int] | None = None
) -> list[UnreliableFont]:
    """Polices composites sans table `/ToUnicode`, page par page.

    Comme les rectangles et les zones opaques : sur le document **d'origine**.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        if pages is None:
            wanted: list[int] = list(range(doc.page_count))
        else:
            wanted = [p for p in pages if 0 <= p < doc.page_count]

        out: list[UnreliableFont] = []
        seen: set[tuple[int, str]] = set()
        for index in wanted:
            for font in doc.load_page(index).get_fonts(full=True):
                xref, subtype, basefont = font[0], str(font[2]), str(font[3])
                encoding = str(font[5] or "")

                needs_tounicode = subtype == "Type3" or encoding.startswith(
                    _OPAQUE_ENCODING_PREFIX
                )
                if not needs_tounicode:
                    continue

                try:
                    kind, _ = doc.xref_get_key(xref, "ToUnicode")
                except Exception:
                    kind = "null"
                if kind != "null":
                    continue

                key = (index, basefont)
                if key in seen:
                    continue
                seen.add(key)
                out.append(UnreliableFont(page=index, name=basefont, subtype=subtype))
        return out
    finally:
        doc.close()


def drop_fully_covered_pages(
    fonts: list[UnreliableFont],
    covering: list[tuple[int, tuple[float, float, float, float]]],
    page_rects: dict[int, tuple[float, float, float, float]],
    *,
    tolerance: float = COVER_TOLERANCE_PT,
) -> list[UnreliableFont]:
    """Retire les polices des pages qu'une règle géométrique couvre entièrement.

    Le seul remède géométrique à une police illisible est de couvrir toute la
    page : contrairement à une zone opaque, on ne sait pas où le texte concerné se
    trouve, puisque justement on ne sait pas le lire.
    """
    covered_pages = set()
    for page, box in covering:
        rect = page_rects.get(page)
        if rect is None:
            continue
        core = pymupdf.Rect(
            rect[0] + tolerance, rect[1] + tolerance, rect[2] - tolerance, rect[3] - tolerance
        )
        if not core.is_empty and _contains(pymupdf.Rect(box), core):
            covered_pages.add(page)
    return [f for f in fonts if f.page not in covered_pages]


def page_rects_of(pdf_bytes: bytes) -> dict[int, tuple[float, float, float, float]]:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        return {
            i: (
                float(doc.load_page(i).rect.x0),
                float(doc.load_page(i).rect.y0),
                float(doc.load_page(i).rect.x1),
                float(doc.load_page(i).rect.y1),
            )
            for i in range(doc.page_count)
        }
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Ce qu'on montre à l'humain : l'image, et rien d'autre
# ---------------------------------------------------------------------------
#
# Rendre la *région de page* au lieu de l'image compose la couche texte par
# dessus, et cette couche est exactement ce que les règles ont su lire. Le
# relecteur voit alors du texte net, en conclut « c'est lisible, tout va bien »,
# et passe à côté du seul objet sur lequel on ne peut rien affirmer. On extrait
# donc les pixels de l'image, seuls.

# Assez pour lire un nom en corps 9 sur une page A4 scannée. Au-delà de quelques
# images distinctes la résolution baisse : trente pages scannées, ce sont trente
# images différentes, et l'application tourne en local, mais la mémoire du
# navigateur n'est pas infinie.
_PREVIEW_STEPS: tuple[tuple[int, int], ...] = ((4, 1600), (12, 1200), (40, 900))
_PREVIEW_FLOOR_PX = 700


def _preview_cap(count: int) -> int:
    for limit, cap in _PREVIEW_STEPS:
        if count <= limit:
            return cap
    return _PREVIEW_FLOOR_PX


def _strip_text(doc: pymupdf.Document) -> pymupdf.Document | None:
    """Une copie du document sans sa couche texte, images et tracés intacts.

    Sert de repli quand l'image n'est pas extractible par référence : elle est
    alors dans le flux d'apparence d'une annotation, ou en ligne dans le contenu
    de la page, et `Pixmap(doc, xref)` ne peut rien en faire. Rendre la région de
    page telle quelle remettrait le texte dans la vignette, c'est-à-dire le défaut
    exact que ce module vient de corriger.

    `apply_redactions` avec `images` et `graphics` à *none* ne retire que le
    texte, ce qui laisse la vignette montrer les pixels et rien d'autre.
    """
    try:
        copy = pymupdf.open("pdf", doc.tobytes())
        for page in copy:
            page.add_redact_annot(page.rect)
            page.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_NONE,
                graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                text=pymupdf.PDF_REDACT_TEXT_REMOVE,
            )
        return copy
    except Exception:
        return None


def _render_region(
    doc: pymupdf.Document, page_number: int, bbox: tuple[float, float, float, float], cap: int
) -> dict[str, str] | None:
    """La région rendue depuis un document déjà débarrassé de son texte."""
    try:
        page = doc.load_page(page_number)
        rect = pymupdf.Rect(*bbox) & page.rect
        if rect.is_empty:
            return None
        longest = max(rect.width, rect.height)
        dpi = 72 if longest <= 0 else max(72, min(600, int(72 * cap / longest)))
        pix = page.get_pixmap(clip=rect, dpi=dpi)
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        return {
            "mime": "image/jpeg",
            "data": base64.b64encode(pix.tobytes("jpeg", jpg_quality=82)).decode("ascii"),
        }
    except Exception:
        return None


def _encode_image(doc: pymupdf.Document, xref: int, cap: int) -> dict[str, str] | None:
    """Les pixels de l'image, réduits à `cap` sur le grand côté, en JPEG base64.

    Passe par un `Pixmap` plutôt que par les octets bruts de `extract_image` : le
    flux d'origine peut être en CMJN, porter un canal alpha ou un masque, et un
    navigateur n'en fera pas toujours quelque chose. Le pixmap normalise tout.
    """
    try:
        pix = pymupdf.Pixmap(doc, xref)
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        if pix.colorspace is None or pix.colorspace.n not in (1, 3):
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        while max(pix.width, pix.height) > cap * 2:
            pix.shrink(1)
        return {
            "mime": "image/jpeg",
            "data": base64.b64encode(pix.tobytes("jpeg", jpg_quality=82)).decode("ascii"),
        }
    except Exception:
        # Une image illisible par le moteur d'image ne doit pas faire échouer la
        # revue : l'interface retombe sur le rendu de page, en le disant.
        return None


def region_previews(
    pdf_bytes: bytes, regions: list[OpaqueRegion]
) -> dict[str, dict[str, str]]:
    """Une vignette par image distincte, indexée par empreinte.

    Indexé par `digest` et non par zone : un bandeau répété sur trente pages,
    ce sont trente zones et une seule image, donc un seul lot de pixels à
    transporter.
    """
    if not regions:
        return {}
    wanted: dict[str, tuple[int, int, tuple[float, float, float, float]]] = {}
    for region in regions:
        if region.digest and region.digest not in wanted:
            wanted[region.digest] = (region.xref, region.page, region.bbox)
    if not wanted:
        return {}

    cap = _preview_cap(len(wanted))
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    stripped: pymupdf.Document | None = None
    try:
        out: dict[str, dict[str, str]] = {}
        for digest, (xref, page_number, bbox) in wanted.items():
            encoded = _encode_image(doc, xref, cap) if xref else None
            if encoded is None:
                # Pas d'objet image atteignable : apparence d'annotation, ou image
                # en ligne dans le contenu. On rend la région, mais sur une copie
                # sans texte, jamais sur la page telle quelle.
                if stripped is None:
                    stripped = _strip_text(doc)
                if stripped is not None:
                    encoded = _render_region(stripped, page_number, bbox, cap)
            if encoded is not None:
                out[digest] = encoded
        return out
    finally:
        if stripped is not None:
            stripped.close()
        doc.close()


def _page_to_image(
    transform: tuple[float, float, float, float, float, float], x: float, y: float
) -> tuple[float, float] | None:
    """Un point de la page ramené dans le carré unité de l'image.

    L'inverse de la matrice de placement, pas une règle de trois : une image peut
    être posée tournée ou retournée, et une règle de trois y placerait le
    rectangle vert au mauvais endroit, ce qui ferait croire couverte une zone qui
    ne l'est pas.
    """
    a, b, c, d, e, f = transform
    det = a * d - b * c
    if abs(det) < 1e-9:
        return None
    px, py = x - e, y - f
    return ((d * px - c * py) / det, (-b * px + a * py) / det)


def covered_in_image(
    region: OpaqueRegion,
    covering: list[tuple[int, tuple[float, float, float, float]]],
) -> list[dict[str, object]]:
    """Les zones déjà traitées qui recoupent la zone, en coordonnées de l'image.

    Normalisé dans [0, 1] : l'interface n'a plus qu'à poser des pourcentages, et
    l'affichage reste juste quelle que soit la taille de la vignette. Découpé aux
    bords de l'image, parce qu'un rectangle qui déborde ne couvre rien de plus.
    """
    out: list[dict[str, object]] = []
    for page, box in covering:
        if page != region.page:
            continue
        corners = [
            _page_to_image(region.transform, x, y)
            for x, y in ((box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3]))
        ]
        if any(c is None for c in corners):
            continue
        xs = [c[0] for c in corners if c is not None]
        ys = [c[1] for c in corners if c is not None]
        x0, x1 = max(0.0, min(xs)), min(1.0, max(xs))
        y0, y1 = max(0.0, min(ys)), min(1.0, max(ys))
        if x1 <= x0 or y1 <= y0:
            continue  # hors de l'image
        out.append(
            {
                "bbox": [round(x0, 5), round(y0, 5), round(x1, 5), round(y1, 5)],
                "source": "manual",
            }
        )
    return out
