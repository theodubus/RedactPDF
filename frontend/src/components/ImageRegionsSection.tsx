import type { ImageRegionsMode } from "../api";

// Que faire d'une zone que les règles textuelles n'ont pas pu lire : une image,
// une police dont l'extraction ne rend pas de l'Unicode. Le choix se fait ici
// parce qu'il change le contrat de l'export, pas seulement son rendu.
//
// Ordre : le défaut d'abord, puis du plus strict au plus permissif.
const MODES: ImageRegionsMode[] = ["review", "block", "ignore"];

export function ImageRegionsSection(props: {
  t: (k: string) => string;
  mode: ImageRegionsMode;
  setMode: (m: ImageRegionsMode) => void;
}) {
  const { t, mode, setMode } = props;

  return (
    <section className="section">
      <div className="sectionTitle">{t("form.section.imageRegions")}</div>
      <div className="segmented" role="radiogroup" aria-label={t("form.section.imageRegions")}>
        {MODES.map((m) => {
          const active = mode === m;
          return (
            <button
              key={m}
              type="button"
              className={active ? "segmentedItem segmentedItemActive" : "segmentedItem"}
              role="radio"
              aria-checked={active}
              title={t(`form.imageRegions.${m}.help`)}
              onClick={() => setMode(m)}
            >
              {t(`form.imageRegions.${m}`)}
            </button>
          );
        })}
      </div>
      <p className="sectionHint">{t(`form.imageRegions.${mode}.help`)}</p>
    </section>
  );
}
