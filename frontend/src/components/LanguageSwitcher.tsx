import { useTranslation } from 'react-i18next'

import { LOCALES, type Locale } from '../api/types'
import { setLocale } from '../i18n'

// Each language is named in itself, so it can be found whatever the current UI language is.
const NATIVE_NAMES: Record<Locale, string> = { en: 'English', pl: 'Polski' }

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation()
  return (
    <div role="group" aria-label={t('language.label')} className="flex gap-1">
      {LOCALES.map((locale) => (
        <button
          key={locale}
          type="button"
          lang={locale}
          aria-label={NATIVE_NAMES[locale]}
          aria-pressed={i18n.resolvedLanguage === locale}
          onClick={() => void setLocale(locale)}
          className="rounded-md px-2 py-1 text-sm font-medium text-slate-600 hover:bg-slate-200 aria-pressed:bg-slate-800 aria-pressed:text-white dark:text-slate-300 dark:hover:bg-slate-700 dark:aria-pressed:bg-slate-100 dark:aria-pressed:text-slate-900"
        >
          {locale.toUpperCase()}
        </button>
      ))}
    </div>
  )
}
