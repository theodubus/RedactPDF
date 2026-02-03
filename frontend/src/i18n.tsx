import React, { createContext, useContext, useMemo, useState } from "react";
import fr from "./locales/fr.json";
import en from "./locales/en.json";

export type Lang = "fr" | "en";

type Dict = Record<string, string>;

const DICTS: Record<Lang, Dict> = { fr, en };

type I18nContextValue = {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string) => string;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider(props: { children: React.ReactNode }) {
  const [lang, setLang] = useState<Lang>("fr");

  const value = useMemo<I18nContextValue>(() => {
    const dict = DICTS[lang];
    const t = (key: string) => dict[key] ?? key;
    return { lang, setLang, t };
  }, [lang]);

  return <I18nContext.Provider value={value}>{props.children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}
