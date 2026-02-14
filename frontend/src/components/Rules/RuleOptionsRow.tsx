import { useI18n } from "../../i18n";
import type { RuleKind } from "../../types/uiRules";
import { RuleKindToggle } from "./RuleKindToggle";

type Props = {
  kind: RuleKind;
  setKind: (k: RuleKind) => void;

  caseSensitive: boolean;
  setCaseSensitive: (v: boolean) => void;

  allowSubwords: boolean;
  setAllowSubwords: (v: boolean) => void;

  ignoreAccents: boolean;
  setIgnoreAccents: (v: boolean) => void;

  multiline: boolean;
  setMultiline: (v: boolean) => void;
};

function OptionPill(props: { active: boolean; label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      className={props.active ? "pill pillActive" : "pill"}
      onClick={props.onClick}
      aria-pressed={props.active}
      disabled={props.disabled}
      style={props.disabled ? { opacity: 0.45, cursor: "not-allowed" } : undefined}
    >
      {props.label}
    </button>
  );
}

export function RuleOptionsRow({
  kind,
  setKind,
  caseSensitive,
  setCaseSensitive,
  allowSubwords,
  setAllowSubwords,
  ignoreAccents,
  setIgnoreAccents,
  multiline,
  setMultiline,
}: Props) {
  const { t } = useI18n();
  const regexEnabled = kind === "regex";

  return (
    <div className="row" style={{ gap: 8, flexWrap: "wrap", marginTop: 8 }}>
      <RuleKindToggle t={t} value={kind} onChange={setKind} />

      <OptionPill
        active={caseSensitive}
        label={t("rules.option.caseSensitive")}
        onClick={() => setCaseSensitive(!caseSensitive)}
      />
      <OptionPill
        active={allowSubwords}
        label={t("rules.option.subword")}
        onClick={() => setAllowSubwords(!allowSubwords)}
      />
      <OptionPill
        active={ignoreAccents}
        label={t("rules.option.ignoreAccents")}
        onClick={() => setIgnoreAccents(!ignoreAccents)}
      />
      <OptionPill
        active={regexEnabled && multiline}
        label={t("rules.option.multiline")}
        disabled={!regexEnabled}
        onClick={() => {
          if (!regexEnabled) return;
          setMultiline(!multiline);
        }}
      />
    </div>
  );
}
