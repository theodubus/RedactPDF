// L'avertissement se donne **avant** l'export, au moment où la combinaison est
// choisie, pas dans le rapport qui suit. Un rapport arrive quand le fichier est
// déjà là et se lit comme une formalité ; ici l'utilisateur peut encore changer
// d'avis, ce qui est le seul moment où l'information sert à quelque chose.
//
// La combinaison visée est « Ignorer » plus les propositions : elle produit des
// rectangles noirs sur un scan, ce qui a l'air traité, alors que ça l'est à
// hauteur de ce qu'un détecteur approximatif a bien voulu trouver. Avoir l'air
// fait est parfois pire que ne rien faire.

export function OcrWarningModal(props: {
  t: (k: string) => string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t, onCancel, onConfirm } = props;

  return (
    <div className="reviewOverlay" role="dialog" aria-modal="true">
      <div className="reviewPanel ocrWarningPanel">
        <div className="reviewTitle">{t("ocrWarning.title")}</div>
        <p>{t("ocrWarning.body")}</p>
        <p>
          <strong>{t("ocrWarning.advice")}</strong>
        </p>
        <div className="reviewActions">
          <button type="button" onClick={onCancel}>
            {t("ocrWarning.back")}
          </button>
          <button type="button" className="primary" onClick={onConfirm}>
            {t("ocrWarning.proceed")}
          </button>
        </div>
      </div>
    </div>
  );
}
