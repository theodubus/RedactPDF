import { describe, expect, it } from "vitest";

import en from "./locales/en.json";
import fr from "./locales/fr.json";

// Il n'y a pas de repli : une clé absente d'un fichier s'affiche telle quelle à
// l'écran, en `review.ocrWarning.title` au milieu de la page. Le contrat
// « mêmes clés des deux côtés » était énoncé et non vérifié ; il l'est ici,
// puisque la panne est silencieuse et ne casse ni le build ni le lint.

const frKeys = Object.keys(fr as Record<string, string>).sort();
const enKeys = Object.keys(en as Record<string, string>).sort();

describe("locales", () => {
  it("porte exactement les mêmes clés des deux côtés", () => {
    expect(enKeys.filter((k) => !frKeys.includes(k))).toEqual([]);
    expect(frKeys.filter((k) => !enKeys.includes(k))).toEqual([]);
  });

  it("ne laisse aucune traduction vide", () => {
    const empty = [...Object.entries(fr), ...Object.entries(en)]
      .filter(([, value]) => typeof value !== "string" || value.trim() === "")
      .map(([key]) => key);

    expect(empty).toEqual([]);
  });
});
