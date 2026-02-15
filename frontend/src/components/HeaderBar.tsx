export function HeaderBar(props: {
  lang: "fr" | "en";
  setLang: (l: "fr" | "en") => void;
  t: (k: string) => string;
  fileName?: string;
  onChangeFile?: () => void;
}) {
  const { lang, setLang, t, fileName, onChangeFile } = props;

  return (
    <header className="topBand">
      <div className="topBandLeft">
        {onChangeFile ? (
          <button type="button" className="pill" onClick={onChangeFile}>
            {t("form.file.change")}
          </button>
        ) : null}
        {fileName ? <div className="topBandFileName">{fileName}</div> : null}
      </div>

      <div className="headerRight">
        <button
          type="button"
          className={lang === "fr" ? "pill pillActive" : "pill"}
          onClick={() => setLang("fr")}
        >
          {t("lang.fr")}
        </button>
        <button
          type="button"
          className={lang === "en" ? "pill pillActive" : "pill"}
          onClick={() => setLang("en")}
        >
          {t("lang.en")}
        </button>
      </div>
    </header>
  );
}
