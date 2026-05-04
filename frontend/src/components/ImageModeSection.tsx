import type { ImageMode } from "../api";

// Default mode first, then ordered by destructiveness.
const MODES: ImageMode[] = ["pixels", "remove", "none"];

export function ImageModeSection(props: {
  t: (k: string) => string;
  mode: ImageMode;
  setMode: (m: ImageMode) => void;
}) {
  const { t, mode, setMode } = props;

  return (
    <section className="section">
      <div className="sectionTitle">{t("form.section.imageMode")}</div>
      <div className="segmented" role="radiogroup" aria-label={t("form.section.imageMode")}>
        {MODES.map((m) => {
          const active = mode === m;
          return (
            <button
              key={m}
              type="button"
              className={active ? "segmentedItem segmentedItemActive" : "segmentedItem"}
              role="radio"
              aria-checked={active}
              title={t(`form.imageMode.${m}.help`)}
              onClick={() => setMode(m)}
            >
              {t(`form.imageMode.${m}`)}
            </button>
          );
        })}
      </div>
    </section>
  );
}
