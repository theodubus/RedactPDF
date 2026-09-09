// Ce que l'utilisateur doit regarder avant qu'un export parte, et pourquoi.
//
// Une seule source : ce que le moteur n'a pas pu lire. Les zones opaques et les
// polices illisibles ne sont connues qu'après un 409, c'est le serveur qui les
// calcule sur le document d'origine.
//
// Les rectangles dessinés à la main n'en font **pas** partie, et une version
// précédente avait tort de les y mettre. Un rectangle *est* l'instruction : le
// dessiner, c'est déjà dire ce qu'on veut supprimer, et l'aperçu le montre déjà
// en place. Redemander « avez-vous bien voulu dessiner ce que vous avez dessiné »
// n'ajoute aucune information, et la friction dépensée là n'est plus disponible
// là où elle sert. Ils reviennent en revanche comme **couverture** : au moment de
// regarder une zone illisible, on montre ce qui y est déjà pris en compte, pour
// que la décision se prenne sur ce qui reste.

export type ReviewItem =
  | {
      kind: "opaque";
      id: string;
      page: number;
      bbox: [number, number, number, number];
      /** Empreinte des pixels : deux zones qui la partagent sont la même image. */
      digest: string;
      pageShare: number;
      textRatio: number;
    }
  | { kind: "font"; id: string; page: number; name: string };

/**
 * Une zone déjà traitée, à dessiner par-dessus la vignette.
 *
 * `source` distingue ce que l'utilisateur a posé lui-même de ce qu'un détecteur
 * a proposé. L'OCR viendra ici quand il existera, et il doit rester distinguable
 * à l'oeil : une proposition automatique ne se lit pas comme une décision.
 */
export type CoveredArea = {
  page: number;
  bbox: [number, number, number, number];
  source: "manual" | "ocr";
};

export type Acknowledgements = {
  acknowledged_regions: { page: number; bbox: number[] }[];
  acknowledged_font_pages: number[];
};

const bboxId = (kind: string, page: number, b: readonly number[]) =>
  `${kind}:${page}:${b.map((v) => v.toFixed(2)).join(",")}`;

type ServerDetail = {
  opaque_regions?: {
    page: number;
    bbox: number[];
    digest?: string;
    page_share?: number;
    text_ratio?: number;
  }[];
  unreliable_fonts?: { page: number; name: string }[];
};

/**
 * Ce que le serveur a refusé de lire, extrait du corps d'un 409.
 *
 * Accepte le corps entier comme le détail seul. FastAPI enveloppe la réponse dans
 * `{ "detail": ... }` et `RedactApiError` transporte le corps tel quel : une
 * première version ne lisait que le niveau racine, le carrousel ne s'ouvrait
 * jamais, et le test unitaire ne l'a pas vu parce qu'il recevait la forme que
 * j'avais imaginée. C'est un passage par le navigateur qui l'a montré.
 */
export function serverReviewItems(body: unknown): ReviewItem[] {
  if (typeof body !== "object" || body === null) return [];
  const wrapped = (body as { detail?: unknown }).detail;
  const detail = typeof wrapped === "object" && wrapped !== null ? wrapped : body;
  const d = detail as ServerDetail;
  const items: ReviewItem[] = [];

  for (const region of d.opaque_regions ?? []) {
    if (!Array.isArray(region.bbox) || region.bbox.length !== 4) continue;
    const bbox = region.bbox as [number, number, number, number];
    items.push({
      kind: "opaque",
      id: bboxId("opaque", region.page, bbox),
      page: region.page,
      bbox,
      digest: typeof region.digest === "string" ? region.digest : "",
      pageShare: typeof region.page_share === "number" ? region.page_share : 0,
      textRatio: typeof region.text_ratio === "number" ? region.text_ratio : 0,
    });
  }

  // Une police illisible ne se localise pas : on ne sait pas où est le texte
  // concerné, puisque justement on ne sait pas le lire. L'acquittement porte donc
  // sur la page entière, et une page n'apparaît qu'une fois même si plusieurs
  // polices y sont en cause.
  const seenPages = new Set<number>();
  for (const font of d.unreliable_fonts ?? []) {
    if (seenPages.has(font.page)) continue;
    seenPages.add(font.page);
    items.push({ kind: "font", id: `font:${font.page}`, page: font.page, name: font.name });
  }

  return items;
}

/** Un écran de revue : une vignette à regarder, et tout ce qu'elle acquitte. */
export type ReviewStep = {
  /** L'élément montré. Les autres pages du groupe portent les mêmes pixels. */
  head: ReviewItem;
  /** Tous les éléments acquittés d'un seul « J'ai vérifié ». */
  members: ReviewItem[];
  /** Pages concernées, dans l'ordre, pour l'affichage. */
  pages: number[];
};

/**
 * Regroupe les zones identiques pour n'en montrer qu'une.
 *
 * Un bandeau d'en-tête sur trente pages, ce sont trente zones et une seule image.
 * Les faire défiler trente fois rendrait la revue si pénible qu'elle serait
 * cliquée sans être faite, ce qui est pire que pas de revue du tout. Le
 * regroupement se fait sur l'empreinte des pixels rendue par le serveur : ce sont
 * littéralement les mêmes octets, donc les regarder une fois suffit, et
 * l'acquittement porte quand même sur chaque page.
 *
 * Sans empreinte (serveur plus ancien, image sans hachage), chaque zone reste
 * seule : on ne regroupe jamais sur une supposition.
 */
export function reviewSteps(items: ReviewItem[]): ReviewStep[] {
  const steps: ReviewStep[] = [];
  const byDigest = new Map<string, ReviewStep>();

  for (const item of items) {
    const key = item.kind === "opaque" && item.digest ? `d:${item.digest}` : null;
    const existing = key === null ? undefined : byDigest.get(key);
    if (existing) {
      existing.members.push(item);
      if (!existing.pages.includes(item.page)) existing.pages.push(item.page);
      continue;
    }
    const step: ReviewStep = { head: item, members: [item], pages: [item.page] };
    steps.push(step);
    if (key !== null) byDigest.set(key, step);
  }

  return steps;
}

export function allConfirmed(steps: ReviewStep[], confirmed: ReadonlySet<string>): boolean {
  return steps.every((step) => confirmed.has(step.head.id));
}

/** Ce qui est déjà traité à l'intérieur d'une zone, pour l'afficher par-dessus. */
export function coverageFor(
  item: ReviewItem,
  covered: CoveredArea[],
): CoveredArea[] {
  if (item.kind !== "opaque") return covered.filter((c) => c.page === item.page);
  const [x0, y0, x1, y1] = item.bbox;
  return covered.filter(
    (c) => c.page === item.page && c.bbox[0] < x1 && c.bbox[2] > x0 && c.bbox[1] < y1 && c.bbox[3] > y0,
  );
}

/**
 * Traduit les éléments confirmés en acquittements pour la requête.
 *
 * Le serveur recalcule les zones et compare : un acquittement inventé ne
 * déverrouille rien. C'est aussi pourquoi les rectangles n'ont jamais eu leur
 * place ici, le serveur n'ayant aucun moyen de distinguer un vrai d'un faux.
 */
export function toAcknowledgements(items: ReviewItem[]): Acknowledgements {
  return {
    acknowledged_regions: items
      .filter((i): i is Extract<ReviewItem, { kind: "opaque" }> => i.kind === "opaque")
      .map((i) => ({ page: i.page, bbox: [...i.bbox] })),
    acknowledged_font_pages: [
      ...new Set(items.filter((i) => i.kind === "font").map((i) => i.page)),
    ],
  };
}
