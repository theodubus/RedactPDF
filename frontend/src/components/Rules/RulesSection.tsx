import { useMemo, useState } from "react";
import type { RuleKind, UiRule } from "../../types/uiRules";
import { newId } from "../../utils/redactionUtils";

import { RuleOptionsRow } from "./RuleOptionsRow";
import { RuleAddBar } from "./RuleAddBar";
import { RulesList } from "./RulesList";
import { EditRuleModal } from "./EditRuleModal";

function kindLabel(t: (k: string) => string, kind: RuleKind | "selection") {
  if (kind === "selection") return t("rules.badge.selection");
  return t("rules.badge.request");
}

function summarizeSelection(text: string) {
  const clean = text.trim();
  const maxLen = 40;
  if (clean.length <= maxLen) return clean;
  const keep = 14;
  return `${clean.slice(0, keep)} ... ${clean.slice(-keep)}`;
}

export function RulesSection(props: {
  t: (k: string) => string;
  rules: UiRule[];
  setRules: React.Dispatch<React.SetStateAction<UiRule[]>>;
  onUserChange: () => void;
  pendingSelectionText: string;
  canAddSelection: boolean;
  onAddSelection: () => void;
}) {
  const { t, rules, setRules, onUserChange, pendingSelectionText, canAddSelection, onAddSelection } = props;

  const [draftKind, setDraftKind] = useState<RuleKind>("exact");
  const [draftValue, setDraftValue] = useState("");

  const [draftCaseSensitive, setDraftCaseSensitive] = useState(false);
  const [draftMultiline, setDraftMultiline] = useState(false);
  const [draftAllowSubwords, setDraftAllowSubwords] = useState(false);
  const [draftIgnoreAccents, setDraftIgnoreAccents] = useState(false);

  const [editingId, setEditingId] = useState<string | null>(null);
  const editingRule = useMemo(
    () => (editingId ? rules.find((r) => r.id === editingId && r.kind !== "selection") ?? null : null),
    [editingId, rules]
  );

  const openEdit = (r: UiRule) => {
    if (r.kind === "selection") return;
    setEditingId(r.id);
  };
  const closeEdit = () => setEditingId(null);

  const onSetDraftKind = (k: RuleKind) => {
    onUserChange();
    setDraftKind(k);
    if (k !== "regex") setDraftMultiline(false);
  };

  const addRule = () => {
    onUserChange();

    const trimmed = draftValue.trim();
    if (!trimmed) return;

    const id = newId();
    const rule: UiRule =
      draftKind === "exact"
        ? {
            id,
            kind: "exact",
            value: trimmed,
            caseSensitive: draftCaseSensitive,
            allowSubwords: draftAllowSubwords,
            ignoreAccents: draftIgnoreAccents,
          }
        : {
            id,
            kind: "regex",
            value: trimmed,
            caseSensitive: draftCaseSensitive,
            multiline: draftMultiline,
            allowSubwords: draftAllowSubwords,
            ignoreAccents: draftIgnoreAccents,
          };

    setRules((prev) => [...prev, rule]);
    setDraftValue("");
  };

  const deleteRule = (id: string) => {
    onUserChange();
    setRules((prev) => prev.filter((r) => r.id !== id));
  };

  const saveEdit = (updated: Omit<UiRule, "id">) => {
    if (!editingRule) return;
    onUserChange();

    setRules((prev) =>
      prev.map((r) => {
        if (r.id !== editingRule.id) return r;
        return { ...updated, id: r.id } as UiRule;
      })
    );

    setEditingId(null);
  };

  const inputPlaceholder =
    draftKind === "exact" ? t("rules.input.placeholder.exact") : t("rules.input.placeholder.regex");

  const onDraftKeyDown: React.KeyboardEventHandler<HTMLInputElement> = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addRule();
    }
  };

  return (
    <section className="section">
      <div className="sectionTitle">{t("form.section.rules")}</div>

      {canAddSelection ? (
        <>
          <button
            type="button"
            className="buttonSecondary"
            onClick={() => {
              onUserChange();
              onAddSelection();
            }}
            title={pendingSelectionText}
          >
            {t("rules.selection.add")}
          </button>

          <div className="muted" style={{ marginTop: 6 }}>
            {t("rules.selection.current")}: <strong>{summarizeSelection(pendingSelectionText)}</strong>
          </div>
        </>
      ) : (
        <>
          <RuleAddBar
            t={t}
            value={draftValue}
            onChangeValue={(v: string) => {
              onUserChange();
              setDraftValue(v);
            }}
            placeholder={inputPlaceholder}
            onAdd={addRule}
            onKeyDown={onDraftKeyDown}
          />

          <details style={{ marginTop: 8 }}>
            <summary className="optionsSummary">{t("rules.options.summary")}</summary>
            <RuleOptionsRow
              kind={draftKind}
              setKind={onSetDraftKind}
              caseSensitive={draftCaseSensitive}
              setCaseSensitive={(v: boolean) => {
                onUserChange();
                setDraftCaseSensitive(v);
              }}
              multiline={draftMultiline}
              setMultiline={(v: boolean) => {
                onUserChange();
                setDraftMultiline(v);
              }}
              allowSubwords={draftAllowSubwords}
              setAllowSubwords={(v: boolean) => {
                onUserChange();
                setDraftAllowSubwords(v);
              }}
              ignoreAccents={draftIgnoreAccents}
              setIgnoreAccents={(v: boolean) => {
                onUserChange();
                setDraftIgnoreAccents(v);
              }}
            />
          </details>
        </>
      )}

      <details style={{ marginTop: 8 }}>
        <summary style={{ cursor: "pointer", fontWeight: 600, userSelect: "none" }}>
          {t("rules.options.summary")}
        </summary>
        <RuleOptionsRow
          kind={draftKind}
          setKind={onSetDraftKind}
          caseSensitive={draftCaseSensitive}
          setCaseSensitive={(v: boolean) => {
            onUserChange();
            setDraftCaseSensitive(v);
          }}
          multiline={draftMultiline}
          setMultiline={(v: boolean) => {
            onUserChange();
            setDraftMultiline(v);
          }}
          allowSubwords={draftAllowSubwords}
          setAllowSubwords={(v: boolean) => {
            onUserChange();
            setDraftAllowSubwords(v);
          }}
          ignoreAccents={draftIgnoreAccents}
          setIgnoreAccents={(v: boolean) => {
            onUserChange();
            setDraftIgnoreAccents(v);
          }}
        />
      </details>

      <button
        type="button"
        className="buttonSecondary"
        disabled={!canAddSelection}
        onClick={() => {
          onUserChange();
          onAddSelection();
        }}
        title={pendingSelectionText || t("rules.selection.none")}
      >
        {t("rules.selection.add")}
      </button>

      {pendingSelectionText ? (
        <div className="muted" style={{ marginTop: 6 }}>
          {t("rules.selection.current")}: <strong>{summarizeSelection(pendingSelectionText)}</strong>
        </div>
      ) : (
        <div className="muted" style={{ marginTop: 6 }}>
          {t("rules.selection.none")}
        </div>
      )}

      <RulesList
        t={t}
        rules={rules}
        kindLabel={(k) => kindLabel(t, k)}
        onEdit={openEdit}
        onDelete={deleteRule}
      />

      <EditRuleModal t={t} rule={editingRule} onClose={closeEdit} onSave={saveEdit} />
    </section>
  );
}
