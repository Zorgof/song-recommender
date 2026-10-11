import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../api/client'
import { useAnswerClarification, useRecommend } from '../api/queries'
import type { Recommendation, RecommendationResponse } from '../api/types'
import { ClarificationPrompt } from '../components/ClarificationPrompt'
import { ErrorMessage } from '../components/ErrorMessage'
import { FeedbackButtons } from '../components/FeedbackButtons'
import { MoodInput } from '../components/MoodInput'
import { RecommendationCard } from '../components/RecommendationCard'
import { ThinkingIndicator } from '../components/ThinkingIndicator'
import { currentLocale } from '../i18n'

// UI states (implementation plan, 2.8); recording and transcribing are added in step 8.
type Phase =
  | { kind: 'input' }
  | { kind: 'thinking' }
  | { kind: 'clarifying'; requestId: string; question: string }
  | { kind: 'result'; recommendation: Recommendation }

// After these, answering again cannot work: the request is gone or not waiting any more.
const DEAD_REQUEST_CODES = new Set(['not_found', 'conflict'])

export function HomePage() {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [phase, setPhase] = useState<Phase>({ kind: 'input' })
  const [error, setError] = useState<unknown>(null)
  const recommend = useRecommend()
  const answerClarification = useAnswerClarification()

  function show(response: RecommendationResponse) {
    setPhase(
      response.status === 'completed'
        ? { kind: 'result', recommendation: response.recommendation }
        : { kind: 'clarifying', requestId: response.request_id, question: response.question },
    )
  }

  async function submit(description: string) {
    setError(null)
    setPhase({ kind: 'thinking' })
    try {
      // The locale decides the language of the explanation and the question (FR-15).
      show(
        await recommend.mutateAsync({
          text: description,
          input_mode: 'text',
          locale: currentLocale(),
        }),
      )
    } catch (err) {
      setError(err)
      setPhase({ kind: 'input' })
    }
  }

  async function answer(requestId: string, question: string, reply: string) {
    setError(null)
    setPhase({ kind: 'thinking' })
    try {
      show(await answerClarification.mutateAsync({ requestId, answer: reply }))
    } catch (err) {
      setError(err)
      const dead = err instanceof ApiError && DEAD_REQUEST_CODES.has(err.code)
      setPhase(dead ? { kind: 'input' } : { kind: 'clarifying', requestId, question })
    }
  }

  function startOver() {
    setError(null)
    setPhase({ kind: 'input' })
  }

  function describeAnother() {
    setText('')
    startOver()
  }

  return (
    <div className="space-y-6">
      <p className="text-slate-600 dark:text-slate-300">{t('app.tagline')}</p>

      {phase.kind === 'input' && (
        <>
          {error !== null && (
            <ErrorMessage
              error={error}
              onRetry={text.trim() ? () => void submit(text.trim()) : undefined}
            />
          )}
          <MoodInput value={text} onChange={setText} onSubmit={(value) => void submit(value)} />
        </>
      )}

      {phase.kind === 'thinking' && <ThinkingIndicator />}

      {phase.kind === 'clarifying' && (
        <>
          {error !== null && <ErrorMessage error={error} />}
          <ClarificationPrompt
            question={phase.question}
            onAnswer={(reply) => void answer(phase.requestId, phase.question, reply)}
            onStartOver={startOver}
          />
        </>
      )}

      {phase.kind === 'result' && (
        <>
          <RecommendationCard song={phase.recommendation} />
          <FeedbackButtons requestId={phase.recommendation.request_id} />
          <button type="button" onClick={describeAnother} className="btn-primary">
            {t('result.again')}
          </button>
        </>
      )}
    </div>
  )
}
