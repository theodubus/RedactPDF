import { useMemo, useState } from "react";
import type { RuleKind, UiRule } from "../../types/uiRules";
import { newId } from "../../utils/redactionUtils";

import { RuleKindToggle } from "./RuleKindToggle";
import { RuleOptionsRow } from "./RuleOptionsRow";
import { RuleAddBar } from "./RuleAddBar";
import { RulesList } from "./RulesList";
import { EditRuleModal } from "./EditRuleModal";

function kindLabel(t: (k: string) => string, kind: RuleKind) {
  return kind === "exact" ? t("rules.badge.exact") : t("rules.badge.regex");
}

export function RulesSection(props: {
  t: (k: string) => string;
  rules: UiRule[];
  setRules: React.Dispatch<React.SetStateAction<UiRule[]>>;
  onUserChange: () => void;
}) {
  const { t, rules, setRules, onUserChange } = props;

  // Draft
  const [draftKind, setDraftKind] = useState<RuleKind>("exact");
  const [draftValue, setDraftValue] = useState("");

  const [draftCaseSensitive, setDraftCaseSensitive] = useState(false);
  const [draftMultiline, setDraftMultiline] = useState(false);
  const [draftAllowSubwords, setDraftAllowSubwords] = useState(false);
  const [draftIgnoreAccents, setDraftIgnoreAccents] = useState(false);

  // Modal edit
  const [editingId, setEditingId] = useState<string | null>(null);
  const editingRule = useMemo(
    () => (editingId ? rules.find((r) => r.id === editingId) ?? null : null),
    [editingId, rules]
  );

  const openEdit = (r: UiRule) => {
    setEditingId(r.id);
  };
  const closeEdit = () => setEditingId(null);

  const resetDraftOptionsToDefaults = (kind: RuleKind) => {
    setDraftCaseSensitive(false);
    setDraftIgnoreAccents(false);
    setDraftAllowSubwords(false);
    setDraftMultiline(false);
    // rien d’autre : multiline n’est affiché que si kind === "regex"
    void kind;
  };

  const onSetDraftKind = (k: RuleKind) => {
    onUserChange();
    setDraftKind(k);
    resetDraftOptionsToDefaults(k);
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
    resetDraftOptionsToDefaults(draftKind);
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

      {/* Type de recherche */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "150px 1fr",
          alignItems: "center",
          columnGap: 12,
          rowGap: 0,
          marginTop: 6,
        }}
      >
        <div className="muted" style={{ fontWeight: 600, lineHeight: "32px" }}>
          {t("rules.label.searchType")}:
        </div>

        <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
          <RuleKindToggle t={t} value={draftKind} onChange={onSetDraftKind} />
        </div>

        {/* Options */}
        <div className="muted" style={{ fontWeight: 600, lineHeight: "32px" }}>
          {t("rules.label.options")}:
        </div>

        <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
          <RuleOptionsRow
            kind={draftKind}
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
        </div>
      </div>

      {/* petit espace avant l’input */}
      <div style={{ height: 8 }} />


      {/* Input + Ajouter sur la même ligne */}
      <RuleAddBar
        t={t}
        kind={draftKind}
        value={draftValue}
        onChangeValue={(v: string) => {
          onUserChange();
          setDraftValue(v);
        }}
        placeholder={inputPlaceholder}
        onAdd={addRule}
        onKeyDown={onDraftKeyDown}
      />

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
