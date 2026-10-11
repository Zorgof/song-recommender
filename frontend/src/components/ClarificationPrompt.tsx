import { useId, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { MAX_TEXT } from './MoodInput'

interface Props {
  question: string
  onAnswer: (answer: string) => void
  onStartOver: () => void
}

export function ClarificationPrompt({ question, onAnswer, onStartOver }: Props) {
  const { t } = useTranslation()
  const id = useId()
  const [answer, setAnswer] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    const trimmed = answer.trim()
    if (trimmed) onAnswer(trimmed)
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-3 rounded-lg bg-white p-6 shadow-sm dark:bg-slate-800"
    >
      <h2 className="text-sm font-semibold tracking-wide text-emerald-700 uppercase dark:text-emerald-400">
        {t('clarification.title')}
      </h2>
      {/* The question is in the UI language of the request (FR-12). */}
      <p className="text-lg">{question}</p>
      <label htmlFor={id} className="block text-sm font-medium">
        {t('clarification.answerLabel')}
      </label>
      <textarea
        id={id}
        value={answer}
        onChange={(event) => setAnswer(event.target.value)}
        maxLength={MAX_TEXT}
        rows={3}
        autoFocus
        className="field"
      />
      <div className="flex flex-wrap gap-3">
        <button type="submit" disabled={!answer.trim()} className="btn-primary">
          {t('clarification.submit')}
        </button>
        <button type="button" onClick={onStartOver} className="btn-secondary">
          {t('clarification.startOver')}
        </button>
      </div>
    </form>
  )
}
