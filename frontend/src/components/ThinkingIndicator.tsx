import { useTranslation } from 'react-i18next'

export function ThinkingIndicator() {
  const { t } = useTranslation()
  return (
    <div
      role="status"
      className="flex items-start gap-4 rounded-lg bg-white p-6 shadow-sm dark:bg-slate-800"
    >
      <span
        aria-hidden="true"
        className="mt-1 size-6 shrink-0 animate-spin rounded-full border-4 border-slate-300 border-t-emerald-600"
      />
      <div>
        <p className="font-semibold">{t('thinking.title')}</p>
        <p className="text-sm text-slate-600 dark:text-slate-300">{t('thinking.hint')}</p>
      </div>
    </div>
  )
}
