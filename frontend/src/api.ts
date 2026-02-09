export type AuditReport = unknown;

export type RedactSuccess = {
  pdfBlob: Blob;
  headers: {
    auditStatus?: string;
    auditMatches?: string;

    // Endpoints historiques
    occurrences?: string;

    // Apply (si exposé côté backend)
    occurrencesSearch?: string;
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

export async function redactApply(params: {
  file: File;
  query: string;
  caseSensitive: boolean;
  wholeWord: boolean;
  presets: Array<"email" | "phone" | "credit_card">;
}): Promise<RedactSuccess> {
  const form = new FormData();
  form.append("file", params.file);

  const trimmed = params.query.trim();
  const hasSearch = trimmed.length > 0;
  const hasPresets = params.presets.length > 0;

  const payload = {
    rects: [],
    search: hasSearch
      ? {
          query: trimmed,
          options: {
            case_sensitive: params.caseSensitive,
            whole_word: params.wholeWord,
          },
          scope: { pages: null },
        }
      : null,
    presets: hasPresets
      ? {
          presets: params.presets,
          scope: { pages: null },
        }
      : null,
    options: {},

    // Champ conservé pour compat (si votre modèle le requiert).
    // Si pas de search, on met un pattern improbable.
    audit: {
      patterns: [hasSearch ? trimmed : "__NO_MATCH__"],
      regex: false,
      case_sensitive: params.caseSensitive,
    },
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

  const occSearch =
    getHeader(resp.headers, "X-Redaction-Search-Occurrences") ??
    getHeader(resp.headers, "X-Redaction-Apply-Occurrences-Search");

  const occPresets =
    getHeader(resp.headers, "X-Redaction-Presets-Occurrences") ??
    getHeader(resp.headers, "X-Redaction-Apply-Occurrences-Presets");

  const occTotal =
    getHeader(resp.headers, "X-Redaction-Apply-Occurrences") ??
    getHeader(resp.headers, "X-Redaction-Apply-Occurrences-Total");

  return {
    pdfBlob: blob,
    headers: {
      auditStatus: getHeader(resp.headers, "X-Redaction-Audit-Status"),
      auditMatches: getHeader(resp.headers, "X-Redaction-Audit-Matches"),
      occurrencesSearch: occSearch,
      occurrencesPresets: occPresets,
      occurrencesTotal: occTotal,
    },
  };
}

export async function redactSearch(params: {
  file: File;
  query: string;
  caseSensitive: boolean;
  wholeWord: boolean;
}): Promise<RedactSuccess> {
  const form = new FormData();
  form.append("file", params.file);

  const payload = {
    query: params.query,
    options: {
      case_sensitive: params.caseSensitive,
      whole_word: params.wholeWord,
    },
    scope: { pages: null },
    apply: {},
    audit: {
      patterns: [params.query],
      regex: false,
      case_sensitive: params.caseSensitive,
    },
  };

  form.append("payload", JSON.stringify(payload));

  const resp = await fetch("/api/redact/search", { method: "POST", body: form });

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
      occurrences: getHeader(resp.headers, "X-Redaction-Search-Occurrences"),
    },
  };
}

export async function redactPresets(params: {
  file: File;
  presets: Array<"email" | "phone" | "credit_card">;
}): Promise<RedactSuccess> {
  const form = new FormData();
  form.append("file", params.file);

  const presetAuditRegex: Record<"email" | "phone" | "credit_card", string> = {
    email: "[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}",
    phone: "(?:\\+?\\d[\\d .()-]{6,}\\d)",
    credit_card: "(?:\\d[ -]*?){13,19}",
  };

  const patterns = params.presets.map((p) => presetAuditRegex[p]);

  const payload = {
    presets: params.presets,
    options: {},
    audit: {
      patterns,
      regex: true,
      case_sensitive: false,
    },
  };

  form.append("payload", JSON.stringify(payload));

  const resp = await fetch("/api/redact/presets", { method: "POST", body: form });

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
      occurrences: getHeader(resp.headers, "X-Redaction-Presets-Occurrences"),
    },
  };
}
