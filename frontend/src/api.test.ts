import { afterEach, describe, expect, it, vi } from "vitest";

import { encryptedReason, exportNotices, redactApply } from "./api";

// Le payload construit ici est la seule chose que le backend verra. Une option
// remplie d'une valeur par défaut de ce côté-ci écrase le défaut du serveur, et
// la version précédente le faisait du mauvais côté : `image_mode: "none"` et les
// trois drapeaux d'assainissement à `false`. Ces tests figent l'omission.

function capturePayload(): () => Record<string, unknown> {
  let seen: Record<string, unknown> = {};
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init: { body: FormData }) => {
      seen = JSON.parse(init.body.get("payload") as string);
      return { ok: true, blob: async () => new Blob(), headers: new Headers() } as unknown as Response;
    }),
  );
  return () => seen;
}

afterEach(() => vi.unstubAllGlobals());

const baseParams = {
  file: new File([new Uint8Array([1])], "a.pdf"),
  rects: [],
  rules: [],
  presets: [],
};

describe("construction du payload", () => {
  it("omet les options non fournies au lieu de les remplir", async () => {
    const payload = capturePayload();
    await redactApply(baseParams);

    expect(payload().options).toEqual({});
  });

  it("n'envoie jamais image_mode 'none' sans qu'on le demande", async () => {
    const payload = capturePayload();
    await redactApply(baseParams);

    const options = payload().options as Record<string, unknown>;
    expect(options.image_mode).toBeUndefined();
    expect(options.sanitize_metadata).toBeUndefined();
  });

  it("transmet ce qui est fourni, y compris un false explicite", async () => {
    const payload = capturePayload();
    await redactApply({ ...baseParams, imageMode: "pixels", sanitizeMetadata: false });

    expect(payload().options).toEqual({ image_mode: "pixels", sanitize_metadata: false });
  });

  it("inverse bien sous-mot en whole_word", async () => {
    const payload = capturePayload();
    await redactApply({
      ...baseParams,
      rules: [
        { kind: "exact", query: "Dupont", caseSensitive: false, allowSubwords: false, ignoreAccents: true },
      ],
    });

    const searches = payload().searches as { options: Record<string, unknown> }[];
    expect(searches[0].options.whole_word).toBe(true);
  });
});

// Le corps d'un 400 « document chiffré ». Les deux formes ci-dessous sont les
// octets réels renvoyés par le backend, relevés sur un PDF AES-256 :
//
//   sans mot de passe      {"detail":{"status":"encrypted","reason":"password_required"}}
//   mauvais mot de passe   {"detail":{"status":"encrypted","reason":"password_incorrect"}}
//
// Cette fonction lit une forme de réponse serveur, exactement comme
// `serverReviewItems`, qui n'avait été testée que contre la forme imaginée : le
// carrousel ne s'ouvrait jamais et le test passait. On teste donc contre la
// mesure, pas contre le souvenir.
describe("encryptedReason", () => {
  it("lit la forme enveloppée par FastAPI", () => {
    expect(encryptedReason({ detail: { status: "encrypted", reason: "password_required" } })).toBe(
      "password_required",
    );
    expect(encryptedReason({ detail: { status: "encrypted", reason: "password_incorrect" } })).toBe(
      "password_incorrect",
    );
  });

  it("accepte aussi la forme nue", () => {
    expect(encryptedReason({ status: "encrypted", reason: "password_incorrect" })).toBe(
      "password_incorrect",
    );
  });

  it("retombe sur password_required quand la raison est inconnue", () => {
    expect(encryptedReason({ detail: { status: "encrypted" } })).toBe("password_required");
  });

  it("rend null sur tout ce qui n'est pas un refus de chiffrement", () => {
    expect(encryptedReason({ detail: { status: "inconclusive", opaque_regions: [] } })).toBeNull();
    expect(encryptedReason({ detail: "Not Found" })).toBeNull();
    expect(encryptedReason(null)).toBeNull();
    expect(encryptedReason("erreur")).toBeNull();
  });
});

// Les en-têtes ci-dessous sont ceux d'une réponse réelle, relevés sur un PDF
// AES-256 portant un champ de signature :
//
//   x-redaction-signatures-removed: 1
//   x-redaction-encryption-removed: 1
//   x-redaction-coverage: complete
//
// Même discipline que pour `encryptedReason` : on teste contre la mesure, pas
// contre la forme imaginée.
describe("exportNotices", () => {
  const h = (o: Record<string, string>) => new Headers(o);

  it("ne dit rien sur un export ordinaire", () => {
    expect(
      exportNotices(
        h({
          "X-Redaction-Signatures-Removed": "0",
          "X-Redaction-Encryption-Removed": "0",
          "X-Redaction-Coverage": "complete",
        }),
      ),
    ).toEqual([]);
  });

  it("signale une signature détruite et un chiffrement retiré", () => {
    expect(
      exportNotices(
        h({
          "X-Redaction-Signatures-Removed": "1",
          "X-Redaction-Encryption-Removed": "1",
          "X-Redaction-Coverage": "complete",
        }),
      ),
    ).toEqual(["signature", "encryption"]);
  });

  it("distingue une revue humaine d'un renoncement explicite", () => {
    expect(exportNotices(h({ "X-Redaction-Coverage": "acknowledged" }))).toEqual([
      "coverageAcknowledged",
    ]);
    expect(exportNotices(h({ "X-Redaction-Coverage": "skipped" }))).toEqual(["coverageSkipped"]);
  });

  it("ne bronche pas sur des en-têtes absents", () => {
    expect(exportNotices(h({}))).toEqual([]);
  });
});
