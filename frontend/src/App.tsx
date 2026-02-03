import React, { useMemo, useState } from "react";
import { useI18n } from "./i18n";
import { redactPresets, redactSearch } from "./api";

type PresetKey = "email" | "phone" | "credit_card";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function JsonBlock(props: { value: unknown }) {
  const [open, setOpen] = useState(true);
  const { t } = useI18n();

  return (
    <div className="jsonBlock">
      <button className="link" onClick={() => setOpen((v) => !v)} type="button">
        {open ? t("debug.hide") : t("debug.show")}
      </button>
      {open ? <pre className="pre">{JSON.stringify(props.value, null, 2)}</pre> : null}
    </div>
  );
}

export default function App() {
  const { lang, setLang, t } = useI18n();

  const [file, setFile] = useState<File | null>(null);

  // Search exact
  const [query, setQuery] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [wholeWord, setWholeWord] = useState(true);

  // Presets (✅ Emails décoché par défaut)
  const [presets, setPresets] = useState<Record<PresetKey, boolean>>({
    email: false,
    phone: false,
    credit_card: false,
  });

  const selectedPresets = useMemo(() => {
    return (Object.keys(presets) as PresetKey[]).filter((k) => presets[k]);
  }, [presets]);

  const [submitting, setSubmitting] = useState(false);

  const [successInfo, setSuccessInfo] = useState<{
    auditStatus?: string;
    auditMatches?: string;

    // Occurrences par étape
    occurrencesSearch: number;
    occurrencesPresets: number;
    occurrencesTotal: number;

    lastBlob?: Blob;
  } | null>(null);

  const [errorInfo, setErrorInfo] = useState<{
    status?: number;
    report?: unknown;
    rawMessage?: string;
  } | null>(null);

  const onPickFile: React.ChangeEventHandler<HTMLInputElement> = (e) => {
    setSuccessInfo(null);
    setErrorInfo(null);

    const f = e.target.files?.[0] ?? null;
    if (!f) {
      setFile(null);
      return;
    }

    const isPdf = f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf");
    if (!isPdf) {
      setFile(null);
      setErrorInfo({ rawMessage: t("form.file.invalidType") });
      return;
    }

    setFile(f);
  };

  const togglePreset = (key: PresetKey) => {
    setPresets((p) => ({ ...p, [key]: !p[key] }));
  };

  const handleSubmit: React.FormEventHandler<HTMLFormElement> = async (e) => {
    e.preventDefault();
    setSuccessInfo(null);
    setErrorInfo(null);

    if (!file) {
      setErrorInfo({ rawMessage: t("form.file.required") });
      return;
    }

    const trimmed = query.trim();
    const hasSearch = trimmed.length > 0;
    const hasPresets = selectedPresets.length > 0;

    if (!hasSearch && !hasPresets) {
      setErrorInfo({ rawMessage: t("form.nothingToDo") });
      return;
    }

    setSubmitting(true);

    try {
      // On enchaîne sur le PDF courant (File) et on conserve le dernier Blob pour le download
      let currentFile: File = file;
      let lastBlob: Blob | undefined;

      let occurrencesSearch = 0;
      let occurrencesPresets = 0;

      let lastAuditStatus: string | undefined;
      let lastAuditMatches: string | undefined;

      // 1) Search (si query renseignée)
      if (hasSearch) {
        const r = await redactSearch({
          file: currentFile,
          query: trimmed,
          caseSensitive,
          wholeWord,
        });

        lastBlob = r.pdfBlob;
        lastAuditStatus = r.headers.auditStatus;
        lastAuditMatches = r.headers.auditMatches;

        occurrencesSearch = Number(r.headers.occurrences ?? "0") || 0;

        // Convertir le résultat en File pour éventuellement enchaîner presets
        currentFile = new File([r.pdfBlob], "tmp-redacted.pdf", { type: "application/pdf" });
      }

      // 2) Presets (si au moins un coché)
      if (hasPresets) {
        const r = await redactPresets({
          file: currentFile,
          presets: selectedPresets,
        });

        lastBlob = r.pdfBlob;
        lastAuditStatus = r.headers.auditStatus;
        lastAuditMatches = r.headers.auditMatches;

        occurrencesPresets = Number(r.headers.occurrences ?? "0") || 0;

        currentFile = new File([r.pdfBlob], "tmp-redacted.pdf", { type: "application/pdf" });
      }

      const occurrencesTotal = occurrencesSearch + occurrencesPresets;

      // Affichage succès + bouton download
      setSuccessInfo({
        auditStatus: lastAuditStatus,
        auditMatches: lastAuditMatches,
        occurrencesSearch,
        occurrencesPresets,
        occurrencesTotal,
        lastBlob,
      });

      // Auto-download conservé (comme demandé)
      if (lastBlob) {
        downloadBlob(lastBlob, "redacted.pdf");
      }
    } catch (err) {
      setErrorInfo({
        status: (err as any)?.status,
        report: (err as any)?.report,
        rawMessage: (err as any)?.message,
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="page">
      <header className="header">
        <div className="headerLeft">
          <div className="title">{t("app.title")}</div>
          <div className="subtitle">{t("app.subtitle")}</div>
        </div>

        <div className="headerRight">
          <button
            type="button"
            className={lang === "fr" ? "pill pillActive" : "pill"}
            onClick={() => setLang("fr")}
          >
            {t("lang.fr")}
          </button>
          <button
            type="button"
            className={lang === "en" ? "pill pillActive" : "pill"}
            onClick={() => setLang("en")}
          >
            {t("lang.en")}
          </button>
        </div>
      </header>

      <main className="main">
        <form className="card" onSubmit={handleSubmit}>
          <section className="section">
            <div className="sectionTitle">{t("form.section.file")}</div>
            <label className="fileRow">
              <input type="file" accept="application/pdf" onChange={onPickFile} />
              <span className="fileHelp">
                {file ? `${t("form.file.selected")}: ${file.name}` : t("form.file.choose")}
              </span>
            </label>
          </section>

          <section className="section">
            <div className="sectionTitle">{t("form.section.search")}</div>
            <input
              className="input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("form.search.query.placeholder")}
              aria-label={t("form.search.query")}
            />
            <div className="row">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={caseSensitive}
                  onChange={(e) => setCaseSensitive(e.target.checked)}
                />
                <span>{t("form.search.caseSensitive")}</span>
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={wholeWord}
                  onChange={(e) => setWholeWord(e.target.checked)}
                />
                <span>{t("form.search.wholeWord")}</span>
              </label>
            </div>
          </section>

          <section className="section">
            <div className="sectionTitle">{t("form.section.presets")}</div>
            <div className="row">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={presets.email}
                  onChange={() => togglePreset("email")}
                />
                <span>{t("form.presets.email")}</span>
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={presets.phone}
                  onChange={() => togglePreset("phone")}
                />
                <span>{t("form.presets.phone")}</span>
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={presets.credit_card}
                  onChange={() => togglePreset("credit_card")}
                />
                <span>{t("form.presets.creditCard")}</span>
              </label>
            </div>
          </section>

          <div className="hint">{t("form.hint")}</div>

          <button className="button" type="submit" disabled={submitting}>
            {submitting ? t("form.submitting") : t("form.submit")}
          </button>
        </form>

        <aside className="card">
          {successInfo ? (
            <div>
              <div className="resultTitle ok">{t("result.success.title")}</div>

              <div className="kv">
                <div className="k">{t("result.success.auditStatus")}</div>
                <div className="v">{successInfo.auditStatus ?? "-"}</div>
              </div>

              <div className="kv">
                <div className="k">{t("result.success.occurrencesSearch")}</div>
                <div className="v">{successInfo.occurrencesSearch}</div>
              </div>

              <div className="kv">
                <div className="k">{t("result.success.occurrencesPresets")}</div>
                <div className="v">{successInfo.occurrencesPresets}</div>
              </div>

              <div className="kv">
                <div className="k">{t("result.success.occurrencesTotal")}</div>
                <div className="v">{successInfo.occurrencesTotal}</div>
              </div>

              {successInfo.lastBlob ? (
                <button
                  className="buttonSecondary"
                  type="button"
                  onClick={() => downloadBlob(successInfo.lastBlob!, "redacted.pdf")}
                >
                  {t("result.success.download")}
                </button>
              ) : null}
            </div>
          ) : null}

          {errorInfo ? (
            <div>
              <div className="resultTitle bad">{t("result.error.title")}</div>

              {errorInfo.status ? (
                <div className="kv">
                  <div className="k">{t("result.error.http")}</div>
                  <div className="v">{errorInfo.status}</div>
                </div>
              ) : null}

              {errorInfo.rawMessage && !errorInfo.report ? (
                <div className="errorBox">{errorInfo.rawMessage}</div>
              ) : null}

              {errorInfo.report ? (
                <div>
                  <div className="smallTitle">{t("result.error.details")}</div>
                  <JsonBlock value={errorInfo.report} />
                </div>
              ) : null}

              {!errorInfo.report && !errorInfo.rawMessage ? (
                <div className="errorBox">{t("result.error.noJson")}</div>
              ) : null}
            </div>
          ) : (
            <div className="muted">{t("form.hint")}</div>
          )}
        </aside>
      </main>
    </div>
  );
}
