export function RuleAddBar(props: {
  t: (k: string) => string;
  value: string;
  onChangeValue: (v: string) => void;
  placeholder: string;
  onAdd: () => void;
  onKeyDown: React.KeyboardEventHandler<HTMLInputElement>;
}) {
  const { t, value, onChangeValue, placeholder, onAdd, onKeyDown } = props;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "100%",
        flexWrap: "nowrap",
      }}
    >
      <input
        className="input"
        value={value}
        onChange={(e) => onChangeValue(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        aria-label={t("rules.input.aria")}
        style={{ flex: "1 1 auto", minWidth: 0, height: 48 }}
      />

      <button
        className="buttonSecondary buttonInline"
        type="button"
        onClick={onAdd}
        style={{
          flex: "0 0 auto",
          width: "auto",
          height: 48,
          paddingInline: 14,
          fontSize: 13,
          whiteSpace: "nowrap",
        }}
      >
        {t("rules.add")}
      </button>
    </div>
  );
}
