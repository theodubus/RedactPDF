export function HeaderBar(props: {
  lang: "fr" | "en";
  setLang: (l: "fr" | "en") => void;
  t: (k: string) => string;
}) {
  const { lang, setLang, t } = props;

  return (
    <header className="header">
      <div className="headerLeft">
        <div className="title">{t("app.title")}</div>
        <div className="subtitle">{t("app.subtitle")}</div>
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
