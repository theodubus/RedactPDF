import { useI18n } from "../../i18n";
import type { RuleKind } from "../../types/uiRules";

type Props = {
  kind: RuleKind;

  caseSensitive: boolean;
  setCaseSensitive: (v: boolean) => void;

  allowSubwords: boolean; // UI "Sous-mot"
  setAllowSubwords: (v: boolean) => void;

  ignoreAccents: boolean;
  setIgnoreAccents: (v: boolean) => void;

  multiline: boolean; // only meaningful when kind === "regex"
  setMultiline: (v: boolean) => void;
};

function OptionPill(props: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      className={props.active ? "pill pillActive" : "pill"}
      onClick={props.onClick}
      aria-pressed={props.active}
    >
      {props.label}
    </button>
  );
}

export function RuleOptionsRow({
  kind,
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

  return (
    <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
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
      {kind === "regex" ? (
        <OptionPill
          active={multiline}
          label={t("rules.option.multiline")}
          onClick={() => setMultiline(!multiline)}
        />
      ) : null}
    </div>
  );
}
