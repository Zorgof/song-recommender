import { useId, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { useSendFeedback } from '../api/queries'
import type { FeedbackOut, Score } from '../api/types'
import { ErrorMessage } from './ErrorMessage'

// The backend accepts up to 1000 characters.
const MAX_COMMENT = 1000

interface Props {
  requestId: string
  // The stored rating, in the history view.
  initial?: FeedbackOut | null
}

/**
 * 👍/👎 plus an optional comment (FR-43). A thumb is sent at once; the comment is sent with
 * "Send". Rating again replaces the earlier rating (ADR-05).
 */
export function FeedbackButtons({ requestId, initial = null }: Props) {
  const { t } = useTranslation()
  const id = useId()
  const [score, setScore] = useState<Score | null>(initial?.score ?? null)
  const [comment, setComment] = useState(initial?.comment ?? '')
  const feedback = useSendFeedback()

  function send(newScore: Score) {
    setScore(newScore)
    feedback.mutate({ requestId, score: newScore, comment: comment.trim() || undefined })
  }

  function sendComment(event: FormEvent) {
    event.preventDefault()
    if (score) send(score)
  }

  const thumbs: { value: Score; icon: string; label: string }[] = [
    { value: 'up', icon: '👍', label: t('feedback.up') },
    { value: 'down', icon: '👎', label: t('feedback.down') },
  ]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{t('feedback.question')}</span>
        {thumbs.map(({ value, icon, label }) => (
          <button
            key={value}
            type="button"
            aria-pressed={score === value}
            disabled={feedback.isPending}
            onClick={() => send(value)}
            className="rounded-full border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100 aria-pressed:border-emerald-600 aria-pressed:bg-emerald-50 aria-pressed:text-emerald-900 dark:border-slate-600 dark:hover:bg-slate-700 dark:aria-pressed:bg-emerald-950 dark:aria-pressed:text-emerald-100"
          >
            <span aria-hidden="true">{icon}</span> {label}
          </button>
        ))}
      </div>

      {score && (
        <form onSubmit={sendComment} className="space-y-2">
          <label htmlFor={id} className="block text-sm font-medium">
            {t('feedback.commentLabel')}
          </label>
          <textarea
            id={id}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={MAX_COMMENT}
            rows={2}
            className="field"
          />
          <button type="submit" disabled={feedback.isPending} className="btn-secondary">
            {feedback.isPending ? t('feedback.sending') : t('feedback.send')}
          </button>
        </form>
      )}

      <div aria-live="polite">
        {feedback.isSuccess && (
          <p className="text-sm text-emerald-700 dark:text-emerald-400">{t('feedback.saved')}</p>
        )}
        {feedback.isIdle && initial && !initial.synced_to_langsmith && (
          <p className="text-sm text-slate-500 dark:text-slate-400">{t('feedback.notSynced')}</p>
        )}
      </div>
      {feedback.isError && <ErrorMessage error={feedback.error} />}
    </div>
  )
}
