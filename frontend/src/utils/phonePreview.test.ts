import { describe, expect, it } from "vitest";

import fixture from "./phoneParity.fixture.json";
import { backendWouldRedactPhone, normalizePhoneCandidate } from "./phonePreview";

// Ce fichier est la moitié frontend d'un contrat en deux moitiés. Le corpus est
// engendré par le backend et vérifié par `backend/tests/test_phone_parity.py` ;
// ici on vérifie que l'aperçu rend exactement les mêmes réponses.
//
// Pourquoi ça compte : un surlignage se lit comme une promesse de caviardage. S'il
// surligne un numéro que le backend ne touchera pas, l'utilisateur reçoit un export
// réussi avec la donnée en clair, et l'audit ne le rattrape pas puisqu'il rejoue le
// même détecteur. C'est le seul fichier du frontend qui porte une garantie.

// Limite connue du corpus, mesurée : retirer la borne de longueur 7-15 chiffres
// de `backendWouldRedactPhone` ne fait échouer aucun cas, parce que libphonenumber
// rejette déjà les mêmes candidats. La borne est donc redondante ici, et le corpus
// ne l'exerce pas. Repasser aux métadonnées `min`, en revanche, est bien détecté.

type Case = { candidate: string; region: string; redacted: boolean };
const cases = fixture.cases as Case[];

describe("parité avec _phone_post_filter", () => {
  it("le corpus est non trivial", () => {
    expect(cases.length).toBeGreaterThanOrEqual(40);
    const redacted = cases.filter((c) => c.redacted).length;
    expect(redacted).toBeGreaterThan(0);
    expect(redacted).toBeLessThan(cases.length);
  });

  it("l'aperçu rend la même réponse que le backend sur chaque cas", () => {
    const mismatches = cases
      .filter((c) => backendWouldRedactPhone(c.candidate, c.region) !== c.redacted)
      .map((c) => `${JSON.stringify(c.candidate)} en ${c.region} : backend=${c.redacted}`);

    expect(mismatches).toEqual([]);
  });
});

describe("normalizePhoneCandidate", () => {
  it("retire les extensions et convertit 00 en +", () => {
    expect(normalizePhoneCandidate("06 12 34 56 78 poste 42")).toBe("0612345678");
    expect(normalizePhoneCandidate("0033612345678")).toBe("+33612345678");
  });
});
