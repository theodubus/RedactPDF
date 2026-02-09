import React, { useMemo, useState } from "react";
import { useI18n } from "./i18n";
import { redactApply } from "./api";
import type { PresetKey, RuleInput } from "./api";

type RuleKind = "exact" | "regex";

type UiRule =
  | {
      id: string;
      kind: "exact";
      value: string;
      caseSensitive: boolean;
      wholeWord: boolean;
    }
  | {
      id: string;
      kind: "regex";
      value: string; // 1 regex
      caseSensitive: boolean;
      multiline: boolean;
    };

function newId(): string {
  const g = (globalThis as any).crypto;
  if (g && typeof g.randomUUID === "function") return g.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

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

function truncate(s: string, max = 56): string {
  const t = (s || "").trim();
  if (t.length <= max) return t;
  return t.slice(0, max - 1) + "…";
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

function kindLabel(t: (k: string) => string, kind: RuleKind) {
  return kind === "exact" ? t("rules.badge.exact") : t("rules.badge.regex");
}

export default function App() {
  const { lang, setLang, t } = useI18n();

  const [file, setFile] = useState<File | null>(null);

  // Draft add-bar
  const [draftKind, setDraftKind] = useState<RuleKind>("exact");
  const [draftValue, setDraftValue] = useState("");

  // Draft options (must be set at add time)
  const [draftCaseSensitive, setDraftCaseSensitive] = useState(false);
  const [draftWholeWord, setDraftWholeWord] = useState(true); // exact only
  const [draftMultiline, setDraftMultiline] = useState(false); // regex only

  // Rules list
  const [rules, setRules] = useState<UiRule[]>([]);

  // Presets
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

  // Modal edit
  const [editingId, setEditingId] = useState<string | null>(null);
  const editingRule = useMemo(
    () => (editingId ? rules.find((r) => r.id === editingId) ?? null : null),
    [editingId, rules]
  );

  const [editKind, setEditKind] = useState<RuleKind>("exact");
  const [editValue, setEditValue] = useState("");
  const [editCaseSensitive, setEditCaseSensitive] = useState(false);
  const [editWholeWord, setEditWholeWord] = useState(true);
  const [editMultiline, setEditMultiline] = useState(false);

  const openEdit = (r: UiRule) => {
    setEditingId(r.id);
    setEditKind(r.kind);
    setEditValue(r.value);
    setEditCaseSensitive(r.caseSensitive);
    if (r.kind === "exact") {
      setEditWholeWord(r.wholeWord);
      setEditMultiline(false);
    } else {
      setEditWholeWord(true);
      setEditMultiline(r.multiline);
    }
  };

  const closeEdit = () => {
    setEditingId(null);
  };

  const saveEdit = () => {
    if (!editingRule) return;
    const trimmed = editValue.trim();
    if (!trimmed) {
      setErrorInfo({ rawMessage: t("rules.error.empty") });
      return;
    }

    setRules((prev) =>
      prev.map((r) => {
        if (r.id !== editingRule.id) return r;

        if (editKind === "exact") {
          return {
            id: r.id,
            kind: "exact",
            value: trimmed,
            caseSensitive: editCaseSensitive,
            wholeWord: editWholeWord,
          } satisfies UiRule;
        }

        return {
          id: r.id,
          kind: "regex",
          value: trimmed,
          caseSensitive: editCaseSensitive,
          multiline: editMultiline,
        } satisfies UiRule;
      })
    );

    setEditingId(null);
  };

  const deleteRule = (id: string) => {
    setRules((prev) => prev.filter((r) => r.id !== id));
  };

  const resetDraftOptionsToDefaults = (kind: RuleKind) => {
    setDraftCaseSensitive(false);
    if (kind === "exact") {
      setDraftWholeWord(true);
      setDraftMultiline(false);
    } else {
      setDraftWholeWord(true);
      setDraftMultiline(false);
    }
  };

  const addRule = () => {
    setSuccessInfo(null);
    setErrorInfo(null);

    const trimmed = draftValue.trim();
    if (!trimmed) {
      setErrorInfo({ rawMessage: t("rules.error.empty") });
      return;
    }

    const id = newId();
    const rule: UiRule =
      draftKind === "exact"
        ? {
            id,
            kind: "exact",
            value: trimmed,
            caseSensitive: draftCaseSensitive,
            wholeWord: draftWholeWord,
          }
        : {
            id,
            kind: "regex",
            value: trimmed,
            caseSensitive: draftCaseSensitive,
            multiline: draftMultiline,
          };

    setRules((prev) => [...prev, rule]);

    // Reset for next potential element (defaults)
    setDraftValue("");
    resetDraftOptionsToDefaults(draftKind);
  };

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

  const rulesForApi: RuleInput[] = useMemo(() => {
    return rules.map((r) => {
      if (r.kind === "exact") {
        return {
          kind: "exact",
          query: r.value,
          caseSensitive: r.caseSensitive,
          wholeWord: r.wholeWord,
        } satisfies RuleInput;
      }
      return {
        kind: "regex",
        pattern: r.value,
        caseSensitive: r.caseSensitive,
        multiline: r.multiline,
      } satisfies RuleInput;
    });
  }, [rules]);

  const hasAnythingToDo = rules.length > 0 || selectedPresets.length > 0;

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

  const inputPlaceholder =
    draftKind === "exact" ? t("rules.input.placeholder.exact") : t("rules.input.placeholder.regex");

  const onDraftKeyDown: React.KeyboardEventHandler<HTMLInputElement> = (e) => {
    if (e.key === "Enter") {
      // Enter = add a rule (not submit)
      e.preventDefault();
      addRule();
    }
  };

  const onSetDraftKind = (k: RuleKind) => {
    setDraftKind(k);
    // Reset options when switching mode (clean UX)
    resetDraftOptionsToDefaults(k);
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
            <div className="sectionTitle">{t("form.section.rules")}</div>

            {/* Segmented toggle */}
            <div className="row" style={{ gap: 8 }}>
              <button
                type="button"
                className={draftKind === "exact" ? "pill pillActive" : "pill"}
                onClick={() => onSetDraftKind("exact")}
              >
                {t("rules.toggle.exact")}
              </button>
              <button
                type="button"
                className={draftKind === "regex" ? "pill pillActive" : "pill"}
                onClick={() => onSetDraftKind("regex")}
              >
                {t("rules.toggle.regex")}
              </button>
            </div>

            {/* Add bar: input + add button on same line, add smaller */}
            <div className="row" style={{ gap: 8, alignItems: "center" }}>
              <input
                className="input"
                value={draftValue}
                onChange={(e) => setDraftValue(e.target.value)}
                onKeyDown={onDraftKeyDown}
                placeholder={inputPlaceholder}
                aria-label={t("rules.input.aria")}
              />
              <button
                className="buttonSecondary"
                type="button"
                onClick={addRule}
                style={{
                  padding: "8px 10px",
                  fontSize: 13,
                  lineHeight: "14px",
                  whiteSpace: "nowrap",
                }}
              >
                {t("rules.add")}
              </button>
            </div>

            {/* Draft options visible at add time */}
            <div className="row" style={{ flexWrap: "wrap", gap: 14, marginTop: 8 }}>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={draftCaseSensitive}
                  onChange={(e) => setDraftCaseSensitive(e.target.checked)}
                />
                <span>{t("rules.option.caseSensitive")}</span>
              </label>

              {draftKind === "exact" ? (
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={draftWholeWord}
                    onChange={(e) => setDraftWholeWord(e.target.checked)}
                  />
                  <span>{t("rules.option.wholeWord")}</span>
                </label>
              ) : (
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={draftMultiline}
                    onChange={(e) => setDraftMultiline(e.target.checked)}
                  />
                  <span>{t("rules.option.multiline")}</span>
                </label>
              )}
            </div>

            {/* Scrollable list container (fixed height, always visible) */}
            <div
              style={{
                marginTop: 10,
                border: "1px solid rgba(0,0,0,0.12)",
                borderRadius: 12,
                padding: 10,
                height: 240,
                overflowY: "auto",
                background: "rgba(255,255,255,0.6)",
              }}
            >
              {rules.length === 0 ? (
                <div className="muted" style={{ padding: 6 }}>
                  {t("rules.empty")}
                </div>
              ) : (
                <div style={{ display: "grid", gap: 8 }}>
                  {rules.map((r) => (
                    <div
                      key={r.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        border: "1px solid rgba(0,0,0,0.10)",
                        borderRadius: 10,
                        padding: "10px 12px",
                        gap: 12,
                      }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div
                          style={{
                            fontWeight: 600,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                          title={r.value}
                        >
                          {truncate(r.value)}
                        </div>
                        {/* Keep ONLY this label (no additional badge/pill) */}
                        <div className="muted" style={{ fontSize: 12 }}>
                          {kindLabel(t, r.kind)}
                        </div>
                      </div>

                      <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                        <button
                          type="button"
                          className="buttonSecondary"
                          onClick={() => openEdit(r)}
                          aria-label={t("rules.item.edit")}
                          title={t("rules.item.edit")}
                        >
                          ✎
                        </button>
                        <button
                          type="button"
                          className="buttonSecondary"
                          onClick={() => deleteRule(r.id)}
                          aria-label={t("rules.item.delete")}
                          title={t("rules.item.delete")}
                        >
                          ✕
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
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
                <div className="k">{t("result.success.occurrencesRegex")}</div>
                <div className="v">{successInfo.occurrencesRegex}</div>
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

        {/* Modal edit */}
        {editingRule ? (
          <div
            role="dialog"
            aria-modal="true"
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(0,0,0,0.35)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: 16,
              zIndex: 50,
            }}
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) closeEdit();
            }}
          >
            <div
              className="card"
              style={{
                width: "min(720px, 100%)",
                maxHeight: "85vh",
                overflow: "auto",
                padding: 16,
              }}
              onMouseDown={(e) => e.stopPropagation()}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                <div style={{ fontSize: 18, fontWeight: 700 }}>{t("modal.edit.title")}</div>
              </div>

              <div style={{ marginTop: 12 }}>
                <div className="sectionTitle" style={{ marginBottom: 8 }}>
                  {t("modal.edit.kind")}
                </div>

                <div className="row" style={{ gap: 8 }}>
                  <button
                    type="button"
                    className={editKind === "exact" ? "pill pillActive" : "pill"}
                    onClick={() => setEditKind("exact")}
                  >
                    {t("rules.toggle.exact")}
                  </button>
                  <button
                    type="button"
                    className={editKind === "regex" ? "pill pillActive" : "pill"}
                    onClick={() => setEditKind("regex")}
                  >
                    {t("rules.toggle.regex")}
                  </button>
                </div>
              </div>

              <div style={{ marginTop: 12 }}>
                <div className="sectionTitle" style={{ marginBottom: 8 }}>
                  {t("modal.edit.value")}
                </div>

                {editKind === "regex" ? (
                  <textarea
                    className="input"
                    style={{ minHeight: 90 }}
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    placeholder={t("rules.input.placeholder.regex")}
                  />
                ) : (
                  <input
                    className="input"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    placeholder={t("rules.input.placeholder.exact")}
                  />
                )}
              </div>

              <div style={{ marginTop: 12 }}>
                <div className="sectionTitle" style={{ marginBottom: 8 }}>
                  {t("modal.edit.options")}
                </div>

                <div className="row" style={{ flexWrap: "wrap", gap: 14 }}>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={editCaseSensitive}
                      onChange={(e) => setEditCaseSensitive(e.target.checked)}
                    />
                    <span>{t("rules.option.caseSensitive")}</span>
                  </label>

                  {editKind === "exact" ? (
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={editWholeWord}
                        onChange={(e) => setEditWholeWord(e.target.checked)}
                      />
                      <span>{t("rules.option.wholeWord")}</span>
                    </label>
                  ) : (
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={editMultiline}
                        onChange={(e) => setEditMultiline(e.target.checked)}
                      />
                      <span>{t("rules.option.multiline")}</span>
                    </label>
                  )}
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 16 }}>
                <button type="button" className="buttonSecondary" onClick={closeEdit}>
                  {t("modal.cancel")}
                </button>
                <button type="button" className="button" onClick={saveEdit}>
                  {t("modal.save")}
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
}
