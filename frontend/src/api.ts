export type AuditReport = unknown;

/** Échec renvoyé par /redact/apply, avec le rapport d'audit quand il y en a un. */
export class RedactApiError extends Error {
  readonly status: number;
  readonly report: AuditReport | null;

  constructor(status: number, report: AuditReport | null) {
    super("AUDIT_FAILED");
    this.name = "RedactApiError";
    this.status = status;
    this.report = report;
  }
}

/** Réglages serveur dont l'aperçu a besoin pour dire la même chose que le backend. */
export type ServerConfig = {
  defaultRegion: string;
  /** Un tesseract système est-il installé ? Il n'est jamais embarqué. */
  ocrAvailable: boolean;
  ocrLanguages: string[];
};

/** Région par défaut du backend (`REDACT_DEFAULT_REGION`), FR sauf configuration. */
export const FALLBACK_REGION = "FR";

export async function fetchConfig(): Promise<ServerConfig> {
  const resp = await fetch("/api/config");
  if (!resp.ok) throw new Error(`config: HTTP ${resp.status}`);
  const data = (await resp.json()) as {
    default_region?: unknown;
    ocr_available?: unknown;
    ocr_languages?: unknown;
  };
  const region = typeof data.default_region === "string" ? data.default_region : FALLBACK_REGION;
  return {
    defaultRegion: region,
    ocrAvailable: data.ocr_available === true,
    ocrLanguages: Array.isArray(data.ocr_languages)
      ? data.ocr_languages.filter((l): l is string => typeof l === "string")
      : [],
  };
}

export type PresetKey = "email" | "phone" | "credit_card";

export type ImageMode = "none" | "remove" | "pixels";

/**
 * Que faire des zones que les règles textuelles n'ont pas pu lire.
 *
 * `review` est le défaut : le serveur rend un 409 portant les zones, l'interface
 * les fait défiler, et l'export repart avec les acquittements. `block` refuse
 * sans recours (mode non interactif : seule une règle géométrique déverrouille).
 * `ignore` exporte sans regarder, et c'est un choix nommé, pas un repli.
 */
export type ImageRegionsMode = "review" | "block" | "ignore";

export type RectInput = {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
};

export type RuleInput =
  | {
      kind: "exact";
      query: string;
      caseSensitive: boolean;
      allowSubwords: boolean;  // UI "Sous-mot"
      ignoreAccents: boolean;
    }
  | {
      kind: "regex";
      pattern: string;
      caseSensitive: boolean;
      multiline: boolean;
      allowSubwords: boolean;  // UI "Sous-mot"
      ignoreAccents: boolean;
    };

export type RedactSuccess = {
  pdfBlob: Blob;
  headers: {
    auditStatus?: string;
    auditMatches?: string;

    occurrencesSearch?: string;
    occurrencesRegex?: string;
    occurrencesPresets?: string;
    occurrencesTotal?: string;
  };
};

function getHeader(headers: Headers, name: string): string | undefined {
  const v = headers.get(name);
  return v === null ? undefined : v;
}

async function parseErrorJson(resp: Response): Promise<AuditReport | null> {
  const ct = resp.headers.get("content-type") || "";
  if (!ct.includes("application/json")) return null;
  try {
    return await resp.json();
  } catch {
    return null;
  }
}


function wrapWholeWordRegex(pattern: string): string {
  const p = pattern.trim();
  if (!p) return p;
  // Ne wrappe pas deux fois si l'utilisateur l'a déjà fait
  if (p.startsWith("(?<!\\w)") && p.endsWith("(?!\\w)")) return p;
  return `(?<!\\w)${p}(?!\\w)`;
}


export async function redactApply(params: {
  file: File;
  rects: RectInput[];
  fullPageRects?: RectInput[];
  rules: RuleInput[];
  presets: PresetKey[];
  imageMode?: ImageMode;
  imageRegions?: ImageRegionsMode;
  ocrProposals?: boolean;
  applyGraphics?: boolean;
  sanitizeMetadata?: boolean;
  removeAnnotations?: boolean;
  removeAttachments?: boolean;
  // Acquittements des zones que le serveur a refusé de lire. Il recalcule les
  // zones pour les vérifier : envoyer n'importe quoi ne débloque rien.
  acknowledgedRegions?: { page: number; bbox: number[] }[];
  acknowledgedFontPages?: number[];
}): Promise<RedactSuccess> {
  const form = new FormData();
  form.append("file", params.file);

  const searches = params.rules
    .filter((r): r is Extract<RuleInput, { kind: "exact" }> => r.kind === "exact")
    .map((r) => ({
      query: r.query.trim(),
      options: {
        case_sensitive: r.caseSensitive,
        whole_word: !r.allowSubwords,     // inversion UI
        ignore_accents: r.ignoreAccents,
      },
      scope: { pages: null as null },
    }))
    .filter((s) => s.query.length > 0);

  const regexes = params.rules
    .filter((r): r is Extract<RuleInput, { kind: "regex" }> => r.kind === "regex")
    .map((r) => {
      const raw = r.pattern.trim();
      const pat = r.allowSubwords ? raw : wrapWholeWordRegex(raw);

      return {
        patterns: [pat],
        case_sensitive: r.caseSensitive,
        multiline: r.multiline,
        ignore_accents: r.ignoreAccents,
        scope: { pages: null as null },
      };

    })
    .filter((rx) => rx.patterns[0].length > 0);

  const hasPresets = params.presets.length > 0;

  // Une option non fournie est **omise**, jamais remplie ici. Le backend a ses
  // propres défauts, tous du côté qui caviarde ; les redéfinir de ce côté-ci en
  // ferait une seconde copie à faire dériver, et la version précédente penchait
  // du mauvais côté : `image_mode` retombait sur "none" et les trois drapeaux
  // d'assainissement sur `false`, c'est-à-dire l'inverse du défaut serveur.
  const options: Record<string, unknown> = {};
  if (params.imageMode !== undefined) options.image_mode = params.imageMode;
  if (params.imageRegions !== undefined) options.image_regions = params.imageRegions;
  if (params.ocrProposals !== undefined) options.ocr_proposals = params.ocrProposals;
  if (params.applyGraphics !== undefined) options.apply_graphics = params.applyGraphics;
  if (params.sanitizeMetadata !== undefined) options.sanitize_metadata = params.sanitizeMetadata;
  if (params.removeAnnotations !== undefined) options.remove_annotations = params.removeAnnotations;
  if (params.removeAttachments !== undefined) options.remove_attachments = params.removeAttachments;

  const payload = {
    rects: params.rects,
    full_page_rects: params.fullPageRects ?? [],
    searches,
    regexes,
    presets: hasPresets ? { presets: params.presets, scope: { pages: null as null } } : null,
    options,
    // audit additionnel facultatif : on laisse null (audit_plan gère déjà search/regex/presets)
    audit: null,
    acknowledged_regions: params.acknowledgedRegions ?? [],
    acknowledged_font_pages: params.acknowledgedFontPages ?? [],
  };

  form.append("payload", JSON.stringify(payload));

  const resp = await fetch("/api/redact/apply", { method: "POST", body: form });

  if (!resp.ok) {
    const report = await parseErrorJson(resp);
    throw new RedactApiError(resp.status, report);
  }

  const blob = await resp.blob();

  return {
    pdfBlob: blob,
    headers: {
      auditStatus: getHeader(resp.headers, "X-Redaction-Audit-Status"),
      auditMatches: getHeader(resp.headers, "X-Redaction-Audit-Matches"),
      occurrencesSearch: getHeader(resp.headers, "X-Redaction-Search-Occurrences"),
      occurrencesRegex: getHeader(resp.headers, "X-Redaction-Regex-Occurrences"),
      occurrencesPresets: getHeader(resp.headers, "X-Redaction-Presets-Occurrences"),
      occurrencesTotal: getHeader(resp.headers, "X-Redaction-Total-Occurrences"),
    },
  };
}
