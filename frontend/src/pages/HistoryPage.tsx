import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router'

import { HISTORY_PAGE_SIZE, useHistory } from '../api/queries'
import type { HistoryItem } from '../api/types'
import { ErrorMessage } from '../components/ErrorMessage'
import { FeedbackButtons } from '../components/FeedbackButtons'
import { RecommendationCard } from '../components/RecommendationCard'
import { formatDateTime } from '../lib/format'

export function HistoryPage() {
  const { t } = useTranslation()
  // The page is kept in the URL (?page=2), so Back and reloading keep it.
  const [searchParams, setSearchParams] = useSearchParams()
  const page = Math.max(1, Number.parseInt(searchParams.get('page') ?? '1', 10) || 1)
  const history = useHistory((page - 1) * HISTORY_PAGE_SIZE)

  function goTo(newPage: number) {
    setSearchParams(newPage > 1 ? { page: String(newPage) } : {})
    window.scrollTo({ top: 0 })
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">{t('history.title')}</h1>

      {history.isPending && <p role="status">{t('history.loading')}</p>}
      {history.isError && (
        <ErrorMessage error={history.error} onRetry={() => void history.refetch()} />
      )}

      {history.data && history.data.total === 0 && (
        <p className="text-slate-600 dark:text-slate-300">{t('history.empty')}</p>
      )}

      {history.data && history.data.total > 0 && (
        <>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('history.count', { count: history.data.total })}
          </p>
          <ol className="space-y-6">
            {history.data.items.map((item) => (
              <li key={item.request_id}>
                <HistoryEntry item={item} />
              </li>
            ))}
          </ol>
          <Pagination
            page={page}
            pages={Math.max(1, Math.ceil(history.data.total / HISTORY_PAGE_SIZE))}
            onChange={goTo}
          />
        </>
      )}
    </div>
  )
}

function HistoryEntry({ item }: { item: HistoryItem }) {
  const { t, i18n } = useTranslation()
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
        <time dateTime={item.created_at}>
          {formatDateTime(item.created_at, i18n.resolvedLanguage ?? 'en')}
        </time>
        {item.input_mode === 'voice' && (
          <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs dark:bg-slate-700">
            {t('history.voice')}
          </span>
        )}
      </div>
      <blockquote className="border-l-4 border-slate-300 pl-3 whitespace-pre-wrap italic dark:border-slate-600">
        {item.input_text}
      </blockquote>
      {item.clarification_question && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-sm">
          <dt className="font-medium">{t('history.question')}</dt>
          <dd>{item.clarification_question}</dd>
          <dt className="font-medium">{t('history.answer')}</dt>
          <dd>{item.clarification_answer}</dd>
        </dl>
      )}
      {/* History lists completed recommendations only, so the song is always there. */}
      {item.title && item.artist && (
        <RecommendationCard song={{ ...item, title: item.title, artist: item.artist }} compact />
      )}
      <FeedbackButtons requestId={item.request_id} initial={item.feedback} />
    </div>
  )
}

interface PaginationProps {
  page: number
  pages: number
  onChange: (page: number) => void
}

function Pagination({ page, pages, onChange }: PaginationProps) {
  const { t } = useTranslation()
  if (pages <= 1) return null
  return (
    <nav
      aria-label={t('history.page', { page, pages })}
      className="flex items-center justify-between gap-4"
    >
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
        className="btn-secondary"
      >
        {t('history.previous')}
      </button>
      <span className="text-sm">{t('history.page', { page, pages })}</span>
      <button
        type="button"
        disabled={page >= pages}
        onClick={() => onChange(page + 1)}
        className="btn-secondary"
      >
        {t('history.next')}
      </button>
    </nav>
  )
}
