// Ce que l'utilisateur doit regarder avant qu'un export parte, et pourquoi.
//
// Deux sources, deux moments. Les rectangles sont connus du client dès le clic :
// personne d'autre ne sait ce que l'utilisateur a dessiné, et un rectangle mal
// placé est un échec qu'aucun audit ne peut attraper, puisqu'il n'y a pas de
// règle textuelle à rejouer. Les zones opaques et les polices illisibles, elles,
// ne sont connues qu'après un 409 : c'est le serveur qui les calcule.
//
// D'où une seule interface alimentée deux fois, plutôt qu'une interface qui
// mélangerait deux niveaux de certitude.

export type ReviewItem =
  | { kind: "rect"; id: string; page: number; bbox: [number, number, number, number] }
  | { kind: "opaque"; id: string; page: number; bbox: [number, number, number, number] }
  | { kind: "font"; id: string; page: number; name: string };

export type Acknowledgements = {
  acknowledged_regions: { page: number; bbox: number[] }[];
  acknowledged_font_pages: number[];
};

const bboxId = (kind: string, page: number, b: readonly number[]) =>
  `${kind}:${page}:${b.map((v) => v.toFixed(2)).join(",")}`;

/** Les rectangles dessinés à la main, à confirmer avant l'envoi. */
export function rectReviewItems(
  rects: { page: number; x0: number; y0: number; x1: number; y1: number }[],
): ReviewItem[] {
  return rects.map((r) => {
    const bbox: [number, number, number, number] = [r.x0, r.y0, r.x1, r.y1];
    return { kind: "rect", id: bboxId("rect", r.page, bbox), page: r.page, bbox };
  });
}

type ServerDetail = {
  opaque_regions?: { page: number; bbox: number[] }[];
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
    items.push({ kind: "opaque", id: bboxId("opaque", region.page, bbox), page: region.page, bbox });
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

export function allConfirmed(items: ReviewItem[], confirmed: ReadonlySet<string>): boolean {
  return items.every((item) => confirmed.has(item.id));
}

/**
 * Traduit les éléments confirmés en acquittements pour la requête.
 *
 * Les rectangles n'y figurent pas : le serveur n'a aucun moyen de vérifier qu'un
 * humain les a regardés, le rectangle *étant* l'instruction. Leur revue est donc
 * purement côté client, et prétendre l'inverse donnerait une fausse garantie.
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
