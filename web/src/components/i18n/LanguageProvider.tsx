"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { messages, type LanguagePreference, type Locale, type MessageKey } from "@/lib/i18n/messages";

const STORAGE_KEY = "codex-webui-language";

interface LanguageContextValue {
  preference: LanguagePreference;
  locale: Locale;
  setPreference: (value: LanguagePreference) => void;
  t: (key: MessageKey) => string;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

function systemLocale(): Locale {
  if (typeof navigator === "undefined") return "en";
  return navigator.language.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<LanguagePreference>("system");
  const [detected, setDetected] = useState<Locale>("en");

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "system" || saved === "zh-CN" || saved === "en") setPreferenceState(saved);
    const update = () => setDetected(systemLocale());
    update();
    window.addEventListener("languagechange", update);
    return () => window.removeEventListener("languagechange", update);
  }, []);

  const locale = preference === "system" ? detected : preference;
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setPreference = useCallback((value: LanguagePreference) => {
    setPreferenceState(value);
    localStorage.setItem(STORAGE_KEY, value);
  }, []);
  const t = useCallback((key: MessageKey) => messages[locale][key], [locale]);
  const value = useMemo(() => ({ preference, locale, setPreference, t }), [preference, locale, setPreference, t]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage(): LanguageContextValue {
  const value = useContext(LanguageContext);
  if (!value) throw new Error("useLanguage must be used within LanguageProvider");
  return value;
}
