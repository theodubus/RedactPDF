export type AuditReport = unknown; // le report est structuré côté backend ; on l’affiche tel quel (JSON)

export type RedactSuccess = {
  pdfBlob: Blob;
  headers: {
    auditStatus?: string;
    auditMatches?: string;
    occurrences?: string;
  };
};

function getHeader(headers: Headers, name: string): string | undefined {
  const v = headers.get(name);
  return v === null ? undefined : v;
}

async function parseErrorJson(resp: Response): Promise<AuditReport | null> {
  const ct = resp.headers.get("content-type") || "";
  if (!ct.includes("application/json")) return null;
  return await resp.json();
}

export async function redactSearch(params: {
  file: File;
  query: string;
  caseSensitive: boolean;
  wholeWord: boolean;
}): Promise<RedactSuccess> {
  const form = new FormData();
  form.append("file", params.file);

  // ✅ Aligné sur backend SearchPayload :
  // {
  //   query: str,
  //   options: { case_sensitive, whole_word },
  //   scope: { pages: null | number[] },
  //   apply: OptionsModel (default_factory côté backend),
  //   audit: { patterns, regex, case_sensitive }
  // }
  const payload = {
    query: params.query,
    options: {
      case_sensitive: params.caseSensitive,
      whole_word: params.wholeWord,
    },
    scope: { pages: null },
    apply: {}, // facultatif (default_factory côté backend), conservé pour cohérence
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

  // Payload backend (d’après votre implémentation) :
  // { presets: [...], options: OptionsModel, audit: AuditModel }
  //
  // Pour l’audit côté UI, on fournit des regex "larges".
  // Le backend fait ses propres filtres robustes (phonenumbers, Luhn) lors de la détection,
  // mais l’audit est une vérification post-export : mieux vaut rester conservateur.
  const presetAuditRegex: Record<"email" | "phone" | "credit_card", string> = {
    email: "[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}",
    phone: "(?:\\+?\\d[\\d .()-]{6,}\\d)",
    credit_card: "(?:\\d[ -]*?){13,19}",
  };

  const patterns = params.presets.map((p) => presetAuditRegex[p]);

  const payload = {
    presets: params.presets,
    options: {}, // default_factory côté backend
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
