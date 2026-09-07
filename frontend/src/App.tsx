import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "./i18nContext";
import { fetchConfig, FALLBACK_REGION, redactApply, RedactApiError } from "./api";
import type { ImageMode, PresetKey, RuleInput } from "./api";

import { HeaderBar } from "./components/HeaderBar";
import { RulesSection } from "./components/Rules/RulesSection";
import { PresetsSection } from "./components/PresetsSection";
import { ImageModeSection } from "./components/ImageModeSection";
import { ResultPanel } from "./components/ResultPanel";
import { PdfViewer } from "./components/PdfViewer";

import type { UiRect, UiRule } from "./types/uiRules";
import { downloadBlob, newId } from "./utils/redactionUtils";
import { useHeartbeat } from "./useHeartbeat";

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
  useHeartbeat();

  const [file, setFile] = useState<File | null>(null);
  const [rules, setRules] = useState<UiRule[]>([]);
  const [pendingSelection, setPendingSelection] = useState<PendingSelection | null>(null);
  const [currentPage, setCurrentPage] = useState<number | null>(null);
  const [pageSizes, setPageSizes] = useState<Record<number, { width: number; height: number }>>({});
  const [isDrawingRect, setIsDrawingRect] = useState(false);
  const [presets, setPresets] = useState<Record<PresetKey, boolean>>(EMPTY_PRESETS);
  const [imageMode, setImageMode] = useState<ImageMode>("pixels");
  const [isDragOver, setIsDragOver] = useState(false);

  const [submitting, setSubmitting] = useState(false);

  // L'aperçu du preset téléphone valide les candidats comme le backend, ce qui
  // suppose la même région par défaut. Tant qu'elle n'est pas connue on retient
  // celle du backend : se tromper de région ferait mentir le surlignage.
  const [defaultRegion, setDefaultRegion] = useState(FALLBACK_REGION);

  useEffect(() => {
    let active = true;
    fetchConfig()
      .then((cfg) => {
        if (active) setDefaultRegion(cfg.defaultRegion);
      })
      .catch(() => {
        // Le repli sur FALLBACK_REGION est déjà en place.
      });
    return () => {
      active = false;
    };
  }, []);


  const [errorInfo, setErrorInfo] = useState<{
    status?: number;
    report?: unknown;
    rawMessage?: string;
  } | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const nextRectangleNumberRef = useRef(1);

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
    return rules.flatMap((r) =>
      r.kind === "selection" ? r.rects : r.kind === "rectangle" ? [r.rect] : []
    );
  }, [rules]);

  const fullPageRectsForApi = useMemo(() => {
    return rules.flatMap((r) => (r.kind === "page" ? [r.rect] : []));
  }, [rules]);

  const hasAnythingToDo = rules.length > 0 || selectedPresets.length > 0;

  const handlePageSizeChange = useCallback((pageNumber: number, size: { width: number; height: number }) => {
    setPageSizes((prev) => {
      const existing = prev[pageNumber];
      if (existing && existing.width === size.width && existing.height === size.height) return prev;
      return { ...prev, [pageNumber]: size };
    });
  }, []);

  const loadPdfFile = (pickedFile: File | null) => {
    clearNotices();

    if (!pickedFile) {
      setFile(null);
      setPendingSelection(null);
      setCurrentPage(null);
      setPageSizes({});
      setIsDrawingRect(false);
      nextRectangleNumberRef.current = 1;
      return;
    }

    const isPdf =
      pickedFile.type === "application/pdf" || pickedFile.name.toLowerCase().endsWith(".pdf");
    if (!isPdf) {
      setFile(null);
      setCurrentPage(null);
      setPageSizes({});
      setIsDrawingRect(false);
      nextRectangleNumberRef.current = 1;
      setErrorInfo({ rawMessage: t("form.file.invalidType") });
      return;
    }

    setFile(pickedFile);
    setPendingSelection(null);
    setCurrentPage(1);
    setPageSizes({});
    setIsDrawingRect(false);
    nextRectangleNumberRef.current = 1;
    setRules([]);
    setPresets(EMPTY_PRESETS);
    setImageMode("pixels");
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


  const addCurrentPageRule = () => {
    const pageNumber = currentPage;
    if (!pageNumber) return;
    clearNotices();

    const exists = rules.some((rule) => rule.kind === "page" && rule.pageNumber === pageNumber);
    if (exists) return;

    const pageSize = pageSizes[pageNumber];
    if (!pageSize) return;

    const newRule: UiRule = {
      id: newId(),
      kind: "page",
      value: `${t("rules.page.title")} ${pageNumber}`,
      pageNumber,
      rect: {
        page: pageNumber - 1,
        x0: 0,
        y0: 0,
        x1: pageSize.width,
        y1: pageSize.height,
      },
    };

    setRules((prev) => [...prev, newRule]);
  };


  const addDrawnRectangleRule = (params: { pageNumber: number; rect: UiRect }) => {
    clearNotices();
    const rectangleNumber = nextRectangleNumberRef.current;
    nextRectangleNumberRef.current += 1;

    const newRule: UiRule = {
      id: newId(),
      kind: "rectangle",
      value: `${t("rules.rectangle.title")} ${rectangleNumber} (${t("rules.page.title")} ${params.pageNumber})`,
      rectangleNumber,
      pageNumber: params.pageNumber,
      rect: params.rect,
    };

    setRules((prev) => [...prev, newRule]);
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
        fullPageRects: fullPageRectsForApi,
        rules: rulesForApi,
        presets: selectedPresets,
        imageMode,
        applyGraphics: imageMode !== "none",
        sanitizeMetadata: true,
        removeAnnotations: true,
        removeAttachments: true,
      });

      downloadBlob(r.pdfBlob, "redacted.pdf");
    } catch (err) {
      setErrorInfo(
        err instanceof RedactApiError
          ? { status: err.status, report: err.report, rawMessage: err.message }
          : { rawMessage: err instanceof Error ? err.message : String(err) },
      );
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
              defaultRegion={defaultRegion}
              t={t}
              onSelectionChange={setPendingSelection}
              onCurrentPageChange={setCurrentPage}
              onPageSizeChange={handlePageSizeChange}
              isDrawingRect={isDrawingRect}
              onAddDrawnRect={addDrawnRectangleRule}
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
              isDrawingRect={isDrawingRect}
              onToggleDrawSelection={() => setIsDrawingRect((prev) => !prev)}
              canCensorPage={!!currentPage && !!pageSizes[currentPage]}
              onCensorPage={addCurrentPageRule}
            />

            <PresetsSection t={t} presets={presets} togglePreset={togglePreset} />

            <ImageModeSection t={t} mode={imageMode} setMode={setImageMode} />
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
