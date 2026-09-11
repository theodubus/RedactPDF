import React, { useMemo, useState } from "react";
import fr from "./locales/fr.json";
import en from "./locales/en.json";
import { I18nContext } from "./i18nContext";
import type { I18nContextValue, Lang } from "./i18nContext";

export type { Lang } from "./i18nContext";

type Dict = Record<string, string>;

const DICTS: Record<Lang, Dict> = { fr, en };

export function I18nProvider(props: { children: React.ReactNode }) {
  const [lang, setLang] = useState<Lang>("fr");

  const value = useMemo<I18nContextValue>(() => {
    const dict = DICTS[lang];
    const t = (key: string) => dict[key] ?? key;
    return { lang, setLang, t };
  }, [lang]);

  return <I18nContext.Provider value={value}>{props.children}</I18nContext.Provider>;
}
