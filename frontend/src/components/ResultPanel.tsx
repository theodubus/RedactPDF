import { JsonBlock } from "./JsonBlock";

// Le backend renvoie des codes, pas des phrases : il ignore la langue de
// l'utilisateur. La table ci-dessous est la seule chose à étendre quand un
// nouveau diagnostic apparaît, et un code inconnu est ignoré plutôt que rendu
// sous forme de clé brute.
const DIAGNOSTIC_KEYS: Record<string, string> = {
  line_break_split: "result.diagnostic.lineBreakSplit",
};

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

  return (
    <div>
      <div className="resultTitle bad">{t("result.error.title")}</div>

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
