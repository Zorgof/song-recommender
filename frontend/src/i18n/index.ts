import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import { LOCALES, type Locale } from '../api/types'
import en from '../locales/en.json'
import pl from '../locales/pl.json'

export const DEFAULT_LOCALE: Locale = 'en'
export const STORAGE_KEY = 'song-recommender.locale'

export const resources = {
  en: { translation: en },
  pl: { translation: pl },
} as const

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (LOCALES as readonly string[]).includes(value)
}

/** FR-4: the stored choice, else the browser language, else English. */
export function detectLocale(): Locale {
  const stored = readStoredLocale()
  if (stored) return stored
  for (const tag of navigator.languages ?? [navigator.language]) {
    const language = tag.toLowerCase().split('-')[0]
    if (isLocale(language)) return language
  }
  return DEFAULT_LOCALE
}

// Storage can be unavailable (private windows, blocked site data); the choice is then not kept.
function readStoredLocale(): Locale | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return isLocale(value) ? value : null
  } catch {
    return null
  }
}

function storeLocale(locale: Locale): void {
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    // See readStoredLocale.
  }
}

/** The UI locale sent with every API request. */
export function currentLocale(): Locale {
  return isLocale(i18n.resolvedLanguage) ? i18n.resolvedLanguage : DEFAULT_LOCALE
}

/** Switch the UI language and remember the choice. */
export async function setLocale(locale: Locale): Promise<void> {
  await i18n.changeLanguage(locale)
  storeLocale(locale)
}

i18n.on('languageChanged', (language) => {
  document.documentElement.lang = language
})

void i18n.use(initReactI18next).init({
  resources,
  lng: detectLocale(),
  fallbackLng: DEFAULT_LOCALE,
  supportedLngs: LOCALES,
  interpolation: {
    // React escapes rendered values.
    escapeValue: false,
  },
})

export default i18n
