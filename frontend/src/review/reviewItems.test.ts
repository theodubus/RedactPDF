import { describe, expect, it } from "vitest";

import {
  allConfirmed,
  rectReviewItems,
  serverReviewItems,
  toAcknowledgements,
} from "./reviewItems";

describe("serverReviewItems", () => {
  it("lit les deux natures du corps d'un 409", () => {
    const items = serverReviewItems({
      opaque_regions: [{ page: 0, bbox: [10, 20, 30, 40] }],
      unreliable_fonts: [{ page: 1, name: "Faux" }],
    });

    expect(items.map((i) => i.kind)).toEqual(["opaque", "font"]);
  });

  it("ne montre qu'une entrée par page pour les polices", () => {
    const items = serverReviewItems({
      unreliable_fonts: [
        { page: 2, name: "A" },
        { page: 2, name: "B" },
        { page: 3, name: "C" },
      ],
    });

    expect(items.map((i) => i.page)).toEqual([2, 3]);
  });

  it("accepte la forme réelle de l'API, enveloppée dans `detail`", () => {
    // Bug attrapé par un passage réel dans le navigateur : `RedactApiError`
    // transporte le corps entier, et FastAPI enveloppe tout dans `detail`. Le
    // carrousel ne s'ouvrait jamais, et ce fichier ne le voyait pas parce qu'il
    // lui donnait la forme imaginée plutôt que la vraie.
    const items = serverReviewItems({
      detail: { opaque_regions: [{ page: 0, bbox: [40, 210, 540, 320] }] },
    });

    expect(items).toHaveLength(1);
    expect(items[0].kind).toBe("opaque");
  });

  it("ignore un corps mal formé plutôt que de planter l'export", () => {
    expect(serverReviewItems(null)).toEqual([]);
    expect(serverReviewItems({ opaque_regions: [{ page: 0, bbox: [1, 2] }] })).toEqual([]);
  });
});

describe("toAcknowledgements", () => {
  it("n'acquitte jamais un rectangle auprès du serveur", () => {
    // Le serveur ne peut pas vérifier qu'un humain a regardé un rectangle : le
    // rectangle *est* l'instruction. Envoyer un acquittement donnerait une
    // garantie que personne ne tient.
    const items = [
      ...rectReviewItems([{ page: 0, x0: 1, y0: 2, x1: 3, y1: 4 }]),
      ...serverReviewItems({ opaque_regions: [{ page: 0, bbox: [5, 6, 7, 8] }] }),
    ];

    const acks = toAcknowledgements(items);
    expect(acks.acknowledged_regions).toEqual([{ page: 0, bbox: [5, 6, 7, 8] }]);
  });

  it("dédoublonne les pages de police", () => {
    const items = serverReviewItems({ unreliable_fonts: [{ page: 4, name: "A" }] });

    expect(toAcknowledgements(items).acknowledged_font_pages).toEqual([4]);
  });
});

describe("allConfirmed", () => {
  const items = serverReviewItems({
    opaque_regions: [{ page: 0, bbox: [1, 2, 3, 4] }],
    unreliable_fonts: [{ page: 1, name: "F" }],
  });

  it("exige chaque élément, pas une validation globale", () => {
    expect(allConfirmed(items, new Set([items[0].id]))).toBe(false);
    expect(allConfirmed(items, new Set(items.map((i) => i.id)))).toBe(true);
  });

  it("un identifiant inventé ne débloque rien", () => {
    expect(allConfirmed(items, new Set(["opaque:0:autre"]))).toBe(false);
  });
});
