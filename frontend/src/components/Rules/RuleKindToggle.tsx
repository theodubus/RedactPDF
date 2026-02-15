import type { RuleKind } from "../../types/uiRules";

export function RuleKindToggle(props: {
  t: (k: string) => string;
  value: RuleKind;
  onChange: (k: RuleKind) => void;
}) {
  const { t, value, onChange } = props;

  return (
    <button
      type="button"
      className={value === "regex" ? "pill pillActive" : "pill"}
      onClick={() => onChange(value === "regex" ? "exact" : "regex")}
      aria-pressed={value === "regex"}
    >
      {t("rules.toggle.regex")}
    </button>
  );
}
