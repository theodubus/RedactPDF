// Nommée pour ce qu'elle promet. « Proposer des zones », pas « lire les images » :
// un détecteur approximatif qui s'annoncerait comme un lecteur ferait exactement
// la promesse que ce projet refuse, et un utilisateur qui lit « les images sont
// traitées » n'ira pas vérifier.
//
// Jamais cochée par défaut, et grisée si aucun tesseract n'est installé : le
// binaire figé vend « un fichier, rien à installer », donc l'absence est le cas
// courant et doit s'expliquer, pas échouer à l'export.

export function OcrSection(props: {
  t: (k: string) => string;
  available: boolean;
  enabled: boolean;
  setEnabled: (v: boolean) => void;
}) {
  const { t, available, enabled, setEnabled } = props;

  return (
    <section className="section">
      <div className="sectionTitle">{t("form.section.ocr")}</div>
      <label className={available ? "checkRow" : "checkRow checkRowDisabled"}>
        <input
          type="checkbox"
          checked={available && enabled}
          disabled={!available}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        <span>{t("form.ocr.label")}</span>
      </label>
      <p className="sectionHint">
        {t(available ? "form.ocr.help" : "form.ocr.unavailable")}
      </p>
    </section>
  );
}
