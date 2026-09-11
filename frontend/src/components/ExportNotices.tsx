import type { ExportNotice } from "../api";

/**
 * Ce que l'export a changé sans qu'on l'ait demandé, dit après coup.
 *
 * Non bloquant, et volontairement : le fichier est déjà téléchargé, la décision
 * est prise, et une confirmation de plus dépenserait de l'attention là où il n'y
 * a plus rien à décider. Ce sont des conséquences à connaître, pas des
 * questions. Une modale les ferait passer pour un incident et serait fermée sans
 * être lue.
 *
 * Le cas qui a motivé cette surface : un contrat signé, caviardé, envoyé, et le
 * destinataire qui constate que la signature n'est plus valide. Le backend le
 * savait, l'interface ne le disait pas, donc l'information n'existait que pour
 * les appelants de l'API.
 */
export function ExportNotices(props: {
  t: (k: string) => string;
  notices: ExportNotice[];
  onDismiss: () => void;
}) {
  const { t, notices, onDismiss } = props;
  if (notices.length === 0) return null;

  return (
    <div className="exportNotices" role="status">
      <div className="exportNoticesHead">
        <span className="smallTitle">{t("notice.title")}</span>
        <button type="button" className="exportNoticesClose" onClick={onDismiss}>
          {t("notice.dismiss")}
        </button>
      </div>
      <ul>
        {notices.map((n) => (
          <li key={n}>{t(`notice.${n}`)}</li>
        ))}
      </ul>
    </div>
  );
}
