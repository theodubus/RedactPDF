import { JsonBlock } from "./JsonBlock";

export function ResultPanel(props: {
  t: (k: string) => string;
  successInfo: {
    auditStatus?: string;
    auditMatches?: string;
    occurrencesSearch: number;
    occurrencesRegex: number;
    occurrencesPresets: number;
    occurrencesTotal: number;
    lastBlob?: Blob;
  } | null;
  errorInfo: { status?: number; report?: unknown; rawMessage?: string } | null;
  onDownload: () => void;
}) {
  const { t, successInfo, errorInfo, onDownload } = props;

  if (successInfo) {
    return (
      <div>
        <div className="resultTitle ok">{t("result.success.title")}</div>

        <div className="kv">
          <div className="k">{t("result.success.auditStatus")}</div>
          <div className="v">{successInfo.auditStatus ?? "-"}</div>
        </div>

        <div className="kv">
          <div className="k">{t("result.success.occurrencesSearch")}</div>
          <div className="v">{successInfo.occurrencesSearch}</div>
        </div>

        <div className="kv">
          <div className="k">{t("result.success.occurrencesRegex")}</div>
          <div className="v">{successInfo.occurrencesRegex}</div>
        </div>

        <div className="kv">
          <div className="k">{t("result.success.occurrencesPresets")}</div>
          <div className="v">{successInfo.occurrencesPresets}</div>
        </div>

        <div className="kv">
          <div className="k">{t("result.success.occurrencesTotal")}</div>
          <div className="v">{successInfo.occurrencesTotal}</div>
        </div>

        {successInfo.lastBlob ? (
          <button className="buttonSecondary" type="button" onClick={onDownload}>
            {t("result.success.download")}
          </button>
        ) : null}
      </div>
    );
  }

  if (errorInfo) {
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

  return null;
}
