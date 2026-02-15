import React, { useMemo, useRef, useState } from "react";
import { useI18n } from "./i18n";
import { redactApply } from "./api";
import type { PresetKey, RuleInput } from "./api";

import { HeaderBar } from "./components/HeaderBar";
import { RulesSection } from "./components/Rules/RulesSection";
import { PresetsSection } from "./components/PresetsSection";
import { ResultPanel } from "./components/ResultPanel";
import { PdfViewer } from "./components/PdfViewer";

import type { UiRect, UiRule } from "./types/uiRules";
import { downloadBlob, newId } from "./utils/redactionUtils";

type PendingSelection = {
  text: string;
  rects: UiRect[];
};

const EMPTY_PRESETS: Record<PresetKey, boolean> = {
  email: false,
  phone: false,
  credit_card: false,
};

export default function App() {
  const { lang, setLang, t } = useI18n();

  const [file, setFile] = useState<File | null>(null);
  const [rules, setRules] = useState<UiRule[]>([]);
  const [pendingSelection, setPendingSelection] = useState<PendingSelection | null>(null);
  const [presets, setPresets] = useState<Record<PresetKey, boolean>>(EMPTY_PRESETS);
  const [isDragOver, setIsDragOver] = useState(false);

  const [submitting, setSubmitting] = useState(false);

  const [errorInfo, setErrorInfo] = useState<{
    status?: number;
    report?: unknown;
    rawMessage?: string;
  } | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const clearNotices = () => {
    setErrorInfo(null);
  };

  const selectedPresets = useMemo(() => {
    return (Object.keys(presets) as PresetKey[]).filter((k) => presets[k]);
  }, [presets]);

  const rulesForApi: RuleInput[] = useMemo(() => {
    const mapped: RuleInput[] = [];
    for (const r of rules) {
      if (r.kind === "exact") {
        mapped.push({
          kind: "exact",
          query: r.value,
          caseSensitive: r.caseSensitive,
          allowSubwords: r.allowSubwords,
          ignoreAccents: r.ignoreAccents,
        });
        continue;
      }
      if (r.kind === "regex") {
        mapped.push({
          kind: "regex",
          pattern: r.value,
          caseSensitive: r.caseSensitive,
          multiline: r.multiline,
          allowSubwords: r.allowSubwords,
          ignoreAccents: r.ignoreAccents,
        });
      }
    }
    return mapped;
  }, [rules]);

  const rectsForApi = useMemo(() => {
    return rules.flatMap((r) => (r.kind === "selection" ? r.rects : []));
  }, [rules]);

  const hasAnythingToDo = rules.length > 0 || selectedPresets.length > 0;

  const loadPdfFile = (pickedFile: File | null) => {
    clearNotices();

    if (!pickedFile) {
      setFile(null);
      setPendingSelection(null);
      return;
    }

    const isPdf =
      pickedFile.type === "application/pdf" || pickedFile.name.toLowerCase().endsWith(".pdf");
    if (!isPdf) {
      setFile(null);
      setErrorInfo({ rawMessage: t("form.file.invalidType") });
      return;
    }

    setFile(pickedFile);
    setPendingSelection(null);
    setRules([]);
    setPresets(EMPTY_PRESETS);
  };

  const onPickFile: React.ChangeEventHandler<HTMLInputElement> = (e) => {
    loadPdfFile(e.target.files?.[0] ?? null);
    e.currentTarget.value = "";
  };

  const togglePreset = (key: PresetKey) => {
    clearNotices();
    setPresets((p) => ({ ...p, [key]: !p[key] }));
  };

  const addPendingSelection = () => {
    if (!pendingSelection) return;
    clearNotices();

    const trimmed = pendingSelection.text.trim();
    if (!trimmed || pendingSelection.rects.length === 0) return;

    const newRule: UiRule = {
      id: newId(),
      kind: "selection",
      value: trimmed,
      rects: pendingSelection.rects,
    };

    setRules((prev) => [...prev, newRule]);
    setPendingSelection(null);
  };

  const handleSubmit: React.FormEventHandler<HTMLFormElement> = async (e) => {
    e.preventDefault();
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
        rects: rectsForApi,
        rules: rulesForApi,
        presets: selectedPresets,
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
    <div className="page pageLayout">
      <input ref={fileInputRef} type="file" accept="application/pdf" onChange={onPickFile} hidden />

      <HeaderBar
        lang={lang}
        setLang={setLang}
        t={t}
        fileName={file?.name}
        onChangeFile={file ? () => fileInputRef.current?.click() : undefined}
      />

      <form className="mainColumns" onSubmit={handleSubmit}>
        <section className="viewerPane">
          {file ? (
            <PdfViewer
              file={file}
              rules={rules}
              presetKeys={selectedPresets}
              t={t}
              onSelectionChange={setPendingSelection}
            />
          ) : (
            <div
              className={`uploadDropZone ${isDragOver ? "uploadDropZoneActive" : ""}`.trim()}
              onDragOver={(e) => {
                e.preventDefault();
                setIsDragOver(true);
              }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setIsDragOver(false);
                loadPdfFile(e.dataTransfer.files?.[0] ?? null);
              }}
            >
              <div className="sectionTitle">{t("viewer.drop.title")}</div>
              <p className="muted">{t("viewer.drop.body")}</p>
              <button
                type="button"
                className="button"
                style={{ width: "min(260px, 100%)" }}
                onClick={() => fileInputRef.current?.click()}
              >
                {t("form.file.choose")}
              </button>
            </div>
          )}
        </section>

        <aside className="toolsPane">
          <div className="toolsPaneContent">
            <RulesSection
              t={t}
              rules={rules}
              setRules={setRules}
              onUserChange={clearNotices}
              pendingSelectionText={pendingSelection?.text ?? ""}
              canAddSelection={!!pendingSelection && pendingSelection.rects.length > 0}
              onAddSelection={addPendingSelection}
            />

            <PresetsSection t={t} presets={presets} togglePreset={togglePreset} />
          </div>

          <button className="button toolsSubmitButton" type="submit" disabled={submitting}>
            {submitting ? t("form.submitting") : t("form.submit")}
          </button>
        </aside>
      </form>

      {errorInfo ? (
        <div className="auditModalOverlay" onMouseDown={() => setErrorInfo(null)}>
          <div className="auditModalPanel" onMouseDown={(e) => e.stopPropagation()}>
            <ResultPanel t={t} errorInfo={errorInfo} />
            <button type="button" className="buttonSecondary" onClick={() => setErrorInfo(null)}>
              {t("modal.cancel")}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
