export type AuditReport = unknown;

export type PresetKey = "email" | "phone" | "credit_card";

export type ImageMode = "none" | "remove" | "pixels";

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
  applyGraphics?: boolean;
  sanitizeMetadata?: boolean;
  removeAnnotations?: boolean;
  removeAttachments?: boolean;
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

  const payload = {
    rects: params.rects,
    full_page_rects: params.fullPageRects ?? [],
    searches,
    regexes,
    presets: hasPresets ? { presets: params.presets, scope: { pages: null as null } } : null,
    options: {
      image_mode: params.imageMode ?? "none",
      apply_graphics: !!params.applyGraphics,
      sanitize_metadata: !!params.sanitizeMetadata,
      remove_annotations: !!params.removeAnnotations,
      remove_attachments: !!params.removeAttachments,
    },
    // audit additionnel facultatif : on laisse null (audit_plan gère déjà search/regex/presets)
    audit: null,
  };

  form.append("payload", JSON.stringify(payload));

  const resp = await fetch("/api/redact/apply", { method: "POST", body: form });

  if (!resp.ok) {
    const report = await parseErrorJson(resp);
    const err = new Error("AUDIT_FAILED");
    (err as any).status = resp.status;
    (err as any).report = report;
    throw err;
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
