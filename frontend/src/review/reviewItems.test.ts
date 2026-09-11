import { describe, expect, it } from "vitest";

import {
  allConfirmed,
  previewUrl,
  reviewSteps,
  serverReviewItems,
  toAcknowledgements,
} from "./reviewItems";
import type { CoveredArea, ReviewItem } from "./reviewItems";

const opaque = (
  page: number,
  digest = "",
  covered: CoveredArea[] = [],
  bbox = [10, 10, 200, 100],
): ReviewItem => ({
  kind: "opaque",
  id: `opaque:${page}:${bbox.map((v) => v.toFixed(2)).join(",")}`,
  page,
  bbox: bbox as [number, number, number, number],
  digest,
  pageShare: 0.5,
  textRatio: 0,
  covered,
});

describe("serverReviewItems", () => {
  it("lit un corps enveloppé par FastAPI dans `detail`", () => {
    // La forme réelle. Une première version ne lisait que le niveau racine et le
    // carrousel ne s'ouvrait jamais ; le test de l'époque recevait la forme
    // imaginée, pas celle du serveur.
    const { items } = serverReviewItems({
      detail: {
        status: "inconclusive",
        opaque_regions: [{ page: 0, bbox: [10, 10, 200, 100], digest: "ab", page_share: 0.9 }],
        unreliable_fonts: [],
      },
    });

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: "opaque", page: 0, digest: "ab", pageShare: 0.9 });
  });

  it("lit aussi un détail nu", () => {
    const { items } = serverReviewItems({ opaque_regions: [{ page: 2, bbox: [0, 0, 50, 50] }] });
    expect(items).toHaveLength(1);
    expect(items[0].page).toBe(2);
  });

  it("récupère les vignettes et les zones déjà couvertes", () => {
    const { items, previews } = serverReviewItems({
      detail: {
        opaque_regions: [
          {
            page: 0,
            bbox: [0, 0, 100, 100],
            digest: "ab",
            covered: [{ bbox: [0, 0, 0.5, 0.5], source: "manual" }],
          },
        ],
        previews: { ab: { mime: "image/jpeg", data: "AAAA" } },
      },
    });

    expect(items[0].kind === "opaque" && items[0].covered).toEqual([
      { bbox: [0, 0, 0.5, 0.5], source: "manual" },
    ]);
    expect(previewUrl(previews.ab)).toBe("data:image/jpeg;base64,AAAA");
  });

  it("ignore une boîte mal formée plutôt que de fabriquer une zone", () => {
    const { items } = serverReviewItems({ opaque_regions: [{ page: 0, bbox: [1, 2] }] });
    expect(items).toEqual([]);
  });

  it("n'ouvre qu'une entrée par page pour les polices illisibles", () => {
    // On ne sait pas *où* est le texte concerné : l'acquittement porte sur la
    // page, deux polices sur la même page ne font pas deux écrans.
    const { items } = serverReviewItems({
      detail: {
        unreliable_fonts: [
          { page: 1, name: "AAAA+Foo" },
          { page: 1, name: "BBBB+Bar" },
          { page: 3, name: "CCCC+Baz" },
        ],
      },
    });
    expect(items.map((i) => i.page)).toEqual([1, 3]);
  });

  it("rend une revue vide sur un corps qui n'est pas un objet", () => {
    expect(serverReviewItems(null)).toEqual({ items: [], previews: {} });
    expect(serverReviewItems("boom")).toEqual({ items: [], previews: {} });
  });
});

describe("reviewSteps", () => {
  it("regroupe les zones qui partagent une empreinte", () => {
    // Un bandeau répété est la même image : un seul écran, mais l'acquittement
    // porte sur les trois pages.
    const steps = reviewSteps([opaque(0, "aa"), opaque(1, "aa"), opaque(2, "aa")]);

    expect(steps).toHaveLength(1);
    expect(steps[0].pages).toEqual([0, 1, 2]);
    expect(steps[0].members).toHaveLength(3);
  });

  it("sépare deux pages qui portent la même image mais pas la même couverture", () => {
    // Même pixels, revue différente : sur l'une un rectangle couvre déjà une
    // partie, sur l'autre non. N'en montrer qu'une cacherait l'écart.
    const withRect = [{ bbox: [0, 0, 0.5, 0.5], source: "manual" } as CoveredArea];
    const steps = reviewSteps([opaque(0, "aa", withRect), opaque(1, "aa", [])]);
    expect(steps).toHaveLength(2);
  });

  it("ne regroupe jamais sans empreinte", () => {
    // Sans empreinte on ne sait pas que ce sont les mêmes pixels. Grouper serait
    // une supposition, et une supposition qui fait sauter une vérification.
    const steps = reviewSteps([opaque(0), opaque(1)]);
    expect(steps).toHaveLength(2);
  });

  it("sépare deux images différentes sur la même page", () => {
    const steps = reviewSteps([
      opaque(0, "aa", [], [0, 0, 100, 100]),
      opaque(0, "bb", [], [200, 0, 300, 100]),
    ]);
    expect(steps).toHaveLength(2);
  });
});

describe("allConfirmed", () => {
  it("exige un clic par écran", () => {
    const steps = reviewSteps([opaque(0, "aa"), opaque(1, "bb")]);
    expect(allConfirmed(steps, new Set([steps[0].head.id]))).toBe(false);
    expect(allConfirmed(steps, new Set(steps.map((s) => s.head.id)))).toBe(true);
  });
});

describe("toAcknowledgements", () => {
  it("acquitte chaque page d'un groupe, pas seulement celle montrée", () => {
    const steps = reviewSteps([opaque(0, "aa"), opaque(1, "aa")]);
    const acks = toAcknowledgements(steps.flatMap((s) => s.members));
    expect(acks.acknowledged_regions.map((r) => r.page)).toEqual([0, 1]);
  });

  it("dédoublonne les pages des polices", () => {
    const items: ReviewItem[] = [
      { kind: "font", id: "font:1", page: 1, name: "A" },
      { kind: "font", id: "font:1b", page: 1, name: "B" },
    ];
    expect(toAcknowledgements(items).acknowledged_font_pages).toEqual([1]);
  });
});
