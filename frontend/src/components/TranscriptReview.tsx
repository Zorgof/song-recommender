import { useTranslation } from 'react-i18next'

import type { Transcription } from '../api/types'
import { languageName } from '../lib/format'
import { MoodInput } from './MoodInput'

interface Props {
  // The (possibly edited) text that will be sent.
  value: string
  onChange: (value: string) => void
  // The transcript as returned by the backend.
  transcript: Transcription
  onSubmit: (text: string) => void
  onRecordAgain: () => void
  onDiscard: () => void
}

/** FR-3: the transcript is shown and can be edited before it is sent. */
export function TranscriptReview({
  value,
  onChange,
  transcript,
  onSubmit,
  onRecordAgain,
  onDiscard,
}: Props) {
  const { t, i18n } = useTranslation()
  const language =
    transcript.language && languageName(transcript.language, i18n.resolvedLanguage ?? 'en')

  return (
    <MoodInput
      value={value}
      onChange={onChange}
      onSubmit={onSubmit}
      label={t('voice.reviewLabel')}
      hint={
        <>
          {t('voice.reviewHint')}
          {language && <> {t('voice.detected', { language })}</>}
        </>
      }
      autoFocus
      actions={
        <>
          <button type="button" onClick={onRecordAgain} className="btn-secondary">
            <span aria-hidden="true">🎤</span> {t('voice.recordAgain')}
          </button>
          <button type="button" onClick={onDiscard} className="btn-secondary">
            {t('voice.discard')}
          </button>
        </>
      }
    />
  )
}
