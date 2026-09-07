import { createContext, useContext } from "react";

export type Lang = "fr" | "en";

export type I18nContextValue = {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string) => string;
};

// Le contexte et le hook vivent hors de i18n.tsx : un module qui exporte à la
// fois un composant et autre chose casse le fast refresh de Vite en dev.
export const I18nContext = createContext<I18nContextValue | null>(null);

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}
