import { JsonBlock } from "./JsonBlock";

// Un 409 n'est pas un 400. Le 400 dit « la donnée visée est toujours dans le
// fichier », le 409 dit « une zone a échappé aux règles, je ne peux rien
// affirmer dessus ». Les confondre sous « audit en erreur » effacerait la seule
// distinction que ce contrat apporte, et ferait chercher une fuite là où il n'y
// en a pas.
const INCONCLUSIVE = 409;

// Et un 500 n'est ni l'un ni l'autre : c'est le moteur qui s'est arrêté, sans
// avoir rien conclu du tout. L'annoncer comme un « audit en erreur » envoie
// chercher une fuite dans un fichier qui n'a même pas été produit.
const CRASHED = 500;

// Le backend renvoie des codes, pas des phrases : il ignore la langue de
// l'utilisateur. La table ci-dessous est la seule chose à étendre quand un
// nouveau diagnostic apparaît, et un code inconnu est ignoré plutôt que rendu
// sous forme de clé brute.
const DIAGNOSTIC_KEYS: Record<string, string> = {
  line_break_split: "result.diagnostic.lineBreakSplit",
};

// Le fichier n'était pas un PDF exploitable. Ce n'est ni un audit en échec ni
// une panne : c'est une entrée que rien ne pouvait traiter, et le dire évite
// d'envoyer l'utilisateur chercher une fuite dans un fichier jamais produit.
function unreadableReason(report: unknown): string | null {
  if (typeof report !== "object" || report === null) return null;
  const wrapped = (report as { detail?: unknown }).detail;
  const detail = (typeof wrapped === "object" && wrapped !== null ? wrapped : report) as {
    status?: unknown;
    reason?: unknown;
  };
  if (detail.status !== "unreadable") return null;
  return detail.reason === "empty" ? "empty" : "notAPdf";
}

function readDiagnostics(report: unknown): string[] {
  if (typeof report !== "object" || report === null) return [];
  const value = (report as { diagnostics?: unknown }).diagnostics;
  if (!Array.isArray(value)) return [];
  return value.filter((code): code is string => typeof code === "string" && code in DIAGNOSTIC_KEYS);
}

export function ResultPanel(props: {
  t: (k: string) => string;
  errorInfo: { status?: number; report?: unknown; rawMessage?: string } | null;
}) {
  const { t, errorInfo } = props;

  if (!errorInfo) return null;

  const diagnostics = readDiagnostics(errorInfo.report);
  const inconclusive = errorInfo.status === INCONCLUSIVE;
  const crashed = errorInfo.status !== undefined && errorInfo.status >= CRASHED;
  const unreadable = unreadableReason(errorInfo.report);

  const title = unreadable
    ? "result.unreadable.title"
    : inconclusive
      ? "result.inconclusive.title"
      : crashed
        ? "result.crashed.title"
        : "result.error.title";

  return (
    <div>
      <div className="resultTitle bad">{t(title)}</div>

      {unreadable ? (
        <div className="errorBox">{t(`result.unreadable.${unreadable}`)}</div>
      ) : null}
      {inconclusive ? <div className="errorBox">{t("result.inconclusive.help")}</div> : null}
      {crashed ? <div className="errorBox">{t("result.crashed.help")}</div> : null}

      {errorInfo.status ? (
        <div className="kv">
          <div className="k">{t("result.error.http")}</div>
          <div className="v">{errorInfo.status}</div>
        </div>
      ) : null}

      {errorInfo.rawMessage && !errorInfo.report ? (
        <div className="errorBox">{errorInfo.rawMessage}</div>
      ) : null}

      {diagnostics.length > 0 ? (
        <div className="errorBox">
          <div className="smallTitle">{t("result.error.why")}</div>
          {diagnostics.map((code) => (
            <div key={code}>
              <p>{t(DIAGNOSTIC_KEYS[code])}</p>
              <p>
                <strong>{t(`${DIAGNOSTIC_KEYS[code]}.action`)}</strong>
              </p>
            </div>
          ))}
        </div>
      ) : null}

      {errorInfo.report ? (
        <div>
          <div className="smallTitle">{t("result.error.details")}</div>
          <JsonBlock value={errorInfo.report} t={t} />
        </div>
      ) : null}

      {!errorInfo.report && !errorInfo.rawMessage ? (
        <div className="errorBox">{t("result.error.noJson")}</div>
      ) : null}
    </div>
  );
}
