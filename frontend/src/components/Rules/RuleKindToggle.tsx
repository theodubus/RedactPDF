import type { RuleKind } from "../../types/uiRules";

export function RuleKindToggle(props: {
  t: (k: string) => string;
  value: RuleKind;
  onChange: (k: RuleKind) => void;
}) {
  const { t, value, onChange } = props;

  return (
    <div className="row" style={{ gap: 8 }}>
      <button
        type="button"
        className={value === "exact" ? "pill pillActive" : "pill"}
        onClick={() => onChange("exact")}
      >
        {t("rules.toggle.exact")}
      </button>
      <button
        type="button"
        className={value === "regex" ? "pill pillActive" : "pill"}
        onClick={() => onChange("regex")}
      >
        {t("rules.toggle.regex")}
      </button>
    </div>
  );
}
