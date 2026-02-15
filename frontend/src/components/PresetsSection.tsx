import type { PresetKey } from "../api";

function PresetPill(props: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  const { active, label, onClick } = props;
  return (
    <button
      type="button"
      className={active ? "pill pillActive" : "pill"}
      aria-pressed={active}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

export function PresetsSection(props: {
  t: (k: string) => string;
  presets: Record<PresetKey, boolean>;
  togglePreset: (k: PresetKey) => void;
}) {
  const { t, presets, togglePreset } = props;

  return (
    <section className="section">
      <div className="sectionTitle">{t("form.section.presets")}</div>
      <div className="row" style={{ marginTop: 0, gap: 8 }}>
        <PresetPill
          active={presets.email}
          label={t("form.presets.email")}
          onClick={() => togglePreset("email")}
        />
        <PresetPill
          active={presets.phone}
          label={t("form.presets.phone")}
          onClick={() => togglePreset("phone")}
        />
        <PresetPill
          active={presets.credit_card}
          label={t("form.presets.creditCard")}
          onClick={() => togglePreset("credit_card")}
        />
      </div>
    </section>
  );
}
