import React, { useMemo, useState } from "react";
import { useI18n } from "./i18n";
import { redactApply } from "./api";
import type { PresetKey, RuleInput } from "./api";

import { HeaderBar } from "./components/HeaderBar";
import { FilePickerSection } from "./components/FilePickerSection";
import { RulesSection } from "./components/Rules/RulesSection";
import { PresetsSection } from "./components/PresetsSection";
import { ResultPanel } from "./components/ResultPanel";

import type { UiRule } from "./types/uiRules";
import { downloadBlob } from "./utils/redactionUtils";

export default function App() {
  const { lang, setLang, t } = useI18n();

  const [file, setFile] = useState<File | null>(null);
  const [rules, setRules] = useState<UiRule[]>([]);
  const [presets, setPresets] = useState<Record<PresetKey, boolean>>({
    email: false,
    phone: false,
    credit_card: false,
  });

  const [submitting, setSubmitting] = useState(false);

  const [successInfo, setSuccessInfo] = useState<{
    auditStatus?: string;
    auditMatches?: string;
    occurrencesSearch: number;
    occurrencesRegex: number;
    occurrencesPresets: number;
    occurrencesTotal: number;
    lastBlob?: Blob;
  } | null>(null);

  const [errorInfo, setErrorInfo] = useState<{
    status?: number;
    report?: unknown;
    rawMessage?: string;
  } | null>(null);

  const clearNotices = () => {
    setSuccessInfo(null);
    setErrorInfo(null);
  };

  const selectedPresets = useMemo(() => {
    return (Object.keys(presets) as PresetKey[]).filter((k) => presets[k]);
  }, [presets]);

  const rulesForApi: RuleInput[] = useMemo(() => {
    return rules.map((r) => {
      if (r.kind === "exact") {
        return {
          kind: "exact",
          query: r.value,
          caseSensitive: r.caseSensitive,
          allowSubwords: r.allowSubwords,
          ignoreAccents: r.ignoreAccents,
        };
      }
      return {
        kind: "regex",
        pattern: r.value,
        caseSensitive: r.caseSensitive,
        multiline: r.multiline,
        allowSubwords: r.allowSubwords,
        ignoreAccents: r.ignoreAccents,
      };
    });
  }, [rules]);

  const hasAnythingToDo = rules.length > 0 || selectedPresets.length > 0;

  const onPickFile: React.ChangeEventHandler<HTMLInputElement> = (e) => {
    clearNotices();

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
    clearNotices();
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

    if (!hasAnythingToDo) {
      setErrorInfo({ rawMessage: t("form.nothingToDo.rules") });
      return;
    }

    setSubmitting(true);

    try {
      const r = await redactApply({
        file,
        rules: rulesForApi,
        presets: selectedPresets,
      });

      const occSearch = Number(r.headers.occurrencesSearch ?? "0") || 0;
      const occRegex = Number(r.headers.occurrencesRegex ?? "0") || 0;
      const occPresets = Number(r.headers.occurrencesPresets ?? "0") || 0;
      const occTotal =
        Number(r.headers.occurrencesTotal ?? "0") || occSearch + occRegex + occPresets;

      setSuccessInfo({
        auditStatus: r.headers.auditStatus,
        auditMatches: r.headers.auditMatches,
        occurrencesSearch: occSearch,
        occurrencesRegex: occRegex,
        occurrencesPresets: occPresets,
        occurrencesTotal: occTotal,
        lastBlob: r.pdfBlob,
      });

      downloadBlob(r.pdfBlob, "redacted.pdf");
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
      <HeaderBar lang={lang} setLang={setLang} t={t} />

      <form className="workspace" onSubmit={handleSubmit}>
        <section className="card viewerCard">
          <FilePickerSection t={t} file={file} onPickFile={onPickFile} />

          <div className="pdfPlaceholder">
            <div className="sectionTitle">{t("viewer.placeholder.title")}</div>
            <p className="muted">{t("viewer.placeholder.body")}</p>
          </div>
        </section>

        <aside className="sidePanel">
          <div className="card">
            <RulesSection
              t={t}
              rules={rules}
              setRules={setRules}
              onUserChange={clearNotices}
            />

            <PresetsSection t={t} presets={presets} togglePreset={togglePreset} />

            <div className="hint">{t("form.hint")}</div>

            <button className="button" type="submit" disabled={submitting}>
              {submitting ? t("form.submitting") : t("form.submit")}
            </button>
          </div>

          <div className="card">
            <ResultPanel
              t={t}
              hintText={t("form.hint")}
              successInfo={successInfo}
              errorInfo={errorInfo}
              onDownload={() => {
                if (successInfo?.lastBlob) downloadBlob(successInfo.lastBlob, "redacted.pdf");
              }}
            />
          </div>
        </aside>
      </form>
    </div>
  );
}
