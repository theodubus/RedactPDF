import { JsonBlock } from "./JsonBlock";

export function ResultPanel(props: {
  t: (k: string) => string;
  errorInfo: { status?: number; report?: unknown; rawMessage?: string } | null;
}) {
  const { t, errorInfo } = props;

  if (!errorInfo) return null;

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
