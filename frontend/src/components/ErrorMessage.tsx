import { useTranslation } from 'react-i18next'

import { errorCode } from '../lib/errors'

interface Props {
  error: unknown
  onRetry?: () => void
}

export function ErrorMessage({ error, onRetry }: Props) {
  const { t } = useTranslation()
  return (
    <div
      role="alert"
      className="rounded-lg border border-red-300 bg-red-50 p-4 text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100"
    >
      <p className="font-semibold">{t('errors.title')}</p>
      <p>{t(`errors.${errorCode(error)}`)}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="btn-secondary mt-3">
          {t('errors.retry')}
        </button>
      )}
    </div>
  )
}
