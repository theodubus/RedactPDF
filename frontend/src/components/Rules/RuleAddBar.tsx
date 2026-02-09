import React from "react";
import type { RuleKind } from "../../types/uiRules";

export function RuleAddBar(props: {
  t: (k: string) => string;
  kind: RuleKind;
  value: string;
  onChangeValue: (v: string) => void;
  placeholder: string;
  onAdd: () => void;
  onKeyDown: React.KeyboardEventHandler<HTMLInputElement>;
}) {
  const { t, value, onChangeValue, placeholder, onAdd, onKeyDown } = props;

  return (
    <div className="row" style={{ gap: 8, alignItems: "center" }}>
      <input
        className="input"
        value={value}
        onChange={(e) => onChangeValue(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        aria-label={t("rules.input.aria")}
      />
      <button
        className="buttonSecondary"
        type="button"
        onClick={onAdd}
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
  );
}
