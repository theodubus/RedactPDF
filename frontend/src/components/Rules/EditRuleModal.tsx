import { useEffect, useMemo, useState } from "react";
import type { RuleKind, UiRule } from "../../types/uiRules";
import { RuleOptionsRow } from "./RuleOptionsRow";

type UiRuleNoId =
  | {
      kind: "exact";
      value: string;
      caseSensitive: boolean;
      allowSubwords: boolean;
      ignoreAccents: boolean;
    }
  | {
      kind: "regex";
      value: string;
      caseSensitive: boolean;
      multiline: boolean;
      allowSubwords: boolean;
      ignoreAccents: boolean;
    };

export function EditRuleModal(props: {
  t: (k: string) => string;
  rule: UiRule | null;
  onClose: () => void;
  onSave: (updated: UiRuleNoId) => void;
}) {
  const { t, rule, onClose, onSave } = props;

  const [editKind, setEditKind] = useState<RuleKind>("exact");
  const [editValue, setEditValue] = useState("");

  const [editCaseSensitive, setEditCaseSensitive] = useState(false);
  const [editMultiline, setEditMultiline] = useState(false);
  const [editAllowSubwords, setEditAllowSubwords] = useState(false);
  const [editIgnoreAccents, setEditIgnoreAccents] = useState(false);

  const isOpen = !!rule && rule.kind !== "selection";

  useEffect(() => {
    if (!rule || rule.kind === "selection") return;

    setEditKind(rule.kind);
    setEditValue(rule.value);
    setEditCaseSensitive(rule.caseSensitive);
    setEditAllowSubwords(rule.allowSubwords);
    setEditIgnoreAccents(rule.ignoreAccents);

    if (rule.kind === "regex") {
      setEditMultiline(rule.multiline);
    } else {
      setEditMultiline(false);
    }
  }, [rule]);

  const canSave = useMemo(() => editValue.trim().length > 0, [editValue]);

  const save = () => {
    if (!rule) return;
    const trimmed = editValue.trim();
    if (!trimmed) return;

    if (editKind === "exact") {
      onSave({
        kind: "exact",
        value: trimmed,
        caseSensitive: editCaseSensitive,
        allowSubwords: editAllowSubwords,
        ignoreAccents: editIgnoreAccents,
      } satisfies UiRuleNoId);
      return;
    }

    onSave({
      kind: "regex",
      value: trimmed,
      caseSensitive: editCaseSensitive,
      multiline: editMultiline,
      allowSubwords: editAllowSubwords,
      ignoreAccents: editIgnoreAccents,
    } satisfies UiRuleNoId);
  };

  if (!isOpen) return null;

  return (
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
        zIndex: 200,
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: "min(820px, 100%)",
          maxHeight: "85vh",
          overflow: "auto",
          padding: 16,
          background: "#fff",
          border: "1px solid #d8dce8",
          borderRadius: 12,
          boxShadow: "0 10px 24px rgba(0,0,0,0.22)",
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
          <div style={{ fontSize: 18, fontWeight: 700 }}>{t("modal.edit.title")}</div>
        </div>

        <div style={{ marginTop: 12 }}>
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

        <details open style={{ marginTop: 10 }}>
          <summary className="optionsSummary">{t("rules.options.summary")}</summary>
          <RuleOptionsRow
            kind={editKind}
            setKind={(nextKind) => {
              setEditKind(nextKind);
              if (nextKind !== "regex") {
                setEditMultiline(false);
              }
            }}
            caseSensitive={editCaseSensitive}
            setCaseSensitive={setEditCaseSensitive}
            multiline={editMultiline}
            setMultiline={setEditMultiline}
            allowSubwords={editAllowSubwords}
            setAllowSubwords={setEditAllowSubwords}
            ignoreAccents={editIgnoreAccents}
            setIgnoreAccents={setEditIgnoreAccents}
          />
        </details>

        <div className="modalActions">
          <button type="button" className="buttonSecondary buttonStretch" onClick={onClose}>
            {t("modal.cancel")}
          </button>

          <button
            type="button"
            className="button buttonStretch"
            onClick={save}
            disabled={!canSave}
          >
            {t("modal.save")}
          </button>
        </div>
      </div>
    </div>
  );
}
