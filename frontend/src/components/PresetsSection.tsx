import type { PresetKey } from "../api";

export function PresetsSection(props: {
  t: (k: string) => string;
  presets: Record<PresetKey, boolean>;
  togglePreset: (k: PresetKey) => void;
}) {
  const { t, presets, togglePreset } = props;

  return (
    <section className="section">
      <div className="sectionTitle">{t("form.section.presets")}</div>
      <div className="row">
        <label className="checkbox">
          <input type="checkbox" checked={presets.email} onChange={() => togglePreset("email")} />
          <span>{t("form.presets.email")}</span>
        </label>

        <label className="checkbox">
          <input type="checkbox" checked={presets.phone} onChange={() => togglePreset("phone")} />
          <span>{t("form.presets.phone")}</span>
        </label>

        <label className="checkbox">
          <input
            type="checkbox"
            checked={presets.credit_card}
            onChange={() => togglePreset("credit_card")}
          />
          <span>{t("form.presets.creditCard")}</span>
        </label>
      </div>
    </section>
  );
}
