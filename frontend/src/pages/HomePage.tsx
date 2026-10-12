import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../api/client'
import { useAnswerClarification, useMeta, useRecommend, useTranscribe } from '../api/queries'
import type { Recommendation, RecommendationResponse, Transcription } from '../api/types'
import { ClarificationPrompt } from '../components/ClarificationPrompt'
import { ErrorMessage } from '../components/ErrorMessage'
import { FeedbackButtons } from '../components/FeedbackButtons'
import { MAX_TEXT, MoodInput } from '../components/MoodInput'
import { RecommendationCard } from '../components/RecommendationCard'
import { ThinkingIndicator } from '../components/ThinkingIndicator'
import { TranscriptReview } from '../components/TranscriptReview'
import { VoiceRecorder } from '../components/VoiceRecorder'
import { currentLocale } from '../i18n'
import { MAX_AUDIO_BYTES, canRecord, recordingFilename } from '../lib/audio'
import type { Recording } from '../lib/useVoiceRecorder'

// UI states (implementation plan, 2.8). `typedText` is what was typed before recording; it is
// restored when the recording is cancelled, fails or is discarded.
interface Reviewing {
  kind: 'reviewing'
  transcript: Transcription
  typedText: string
}

type Phase =
  | { kind: 'input' }
  | { kind: 'recording'; typedText: string; returnTo: { kind: 'input' } | Reviewing }
  | { kind: 'transcribing' }
  | Reviewing
  | { kind: 'thinking' }
  | { kind: 'clarifying'; requestId: string; question: string }
  | { kind: 'result'; recommendation: Recommendation }

// After these, answering again cannot work: the request is gone or not waiting any more.
const DEAD_REQUEST_CODES = new Set(['not_found', 'conflict'])
// Sending the same recording again cannot help after these.
const BAD_RECORDING_CODES = new Set([
  'audio_too_large',
  'unsupported_audio_format',
  'invalid_audio',
])

interface Failure {
  error: unknown
  // What "Try again" repeats, if repeating can help.
  retry?: () => void
}

export function HomePage() {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [phase, setPhase] = useState<Phase>({ kind: 'input' })
  const [failure, setFailure] = useState<Failure | null>(null)
  const [nothingHeard, setNothingHeard] = useState(false)
  const meta = useMeta()
  const recommend = useRecommend()
  const answerClarification = useAnswerClarification()
  const transcribe = useTranscribe()

  // FR-32: no microphone when STT is off; NFR-4: none outside a secure context.
  const sttEnabled = meta.data?.stt.enabled === true
  const micAvailable = sttEnabled && canRecord()

  function show(response: RecommendationResponse) {
    setPhase(
      response.status === 'completed'
        ? { kind: 'result', recommendation: response.recommendation }
        : { kind: 'clarifying', requestId: response.request_id, question: response.question },
    )
  }

  function resetMessages() {
    setFailure(null)
    setNothingHeard(false)
  }

  async function submit(description: string, review?: Reviewing) {
    resetMessages()
    setPhase({ kind: 'thinking' })
    try {
      // The locale decides the language of the explanation and the question (FR-15).
      show(
        await recommend.mutateAsync({
          text: description,
          locale: currentLocale(),
          // FR-40: the raw transcript goes to the trace next to the edited text.
          ...(review
            ? { input_mode: 'voice', transcript: review.transcript.text }
            : { input_mode: 'text' }),
        }),
      )
    } catch (error) {
      setFailure({ error, retry: () => void submit(description, review) })
      setPhase(review ?? { kind: 'input' })
    }
  }

  async function answer(requestId: string, question: string, reply: string) {
    resetMessages()
    setPhase({ kind: 'thinking' })
    try {
      show(await answerClarification.mutateAsync({ requestId, answer: reply }))
    } catch (error) {
      // No retry button: the answer field stays, so the user can send it again.
      setFailure({ error })
      const dead = error instanceof ApiError && DEAD_REQUEST_CODES.has(error.code)
      setPhase(dead ? { kind: 'input' } : { kind: 'clarifying', requestId, question })
    }
  }

  function startRecording(from: { kind: 'input' } | Reviewing) {
    resetMessages()
    const typedText = from.kind === 'reviewing' ? from.typedText : text
    setPhase({ kind: 'recording', typedText, returnTo: from })
  }

  async function transcribeRecording(recording: Recording, typedText: string) {
    const backToTyping = () => {
      setText(typedText)
      setPhase({ kind: 'input' })
    }
    if (recording.blob.size > MAX_AUDIO_BYTES) {
      setFailure({ error: new ApiError('audio_too_large', 'The recording is over 10 MB.', 0) })
      backToTyping()
      return
    }
    setPhase({ kind: 'transcribing' })
    try {
      const transcript = await transcribe.mutateAsync({
        audio: recording.blob,
        filename: recordingFilename(recording.blob.type),
      })
      if (!transcript.text.trim()) {
        setNothingHeard(true)
        backToTyping()
        return
      }
      setText(transcript.text.slice(0, MAX_TEXT))
      setPhase({ kind: 'reviewing', transcript, typedText })
    } catch (error) {
      const badRecording = error instanceof ApiError && BAD_RECORDING_CODES.has(error.code)
      setFailure({
        error,
        retry: badRecording ? undefined : () => void transcribeRecording(recording, typedText),
      })
      backToTyping()
    }
  }

  function startOver() {
    resetMessages()
    setPhase({ kind: 'input' })
  }

  function describeAnother() {
    setText('')
    startOver()
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <p className="text-slate-600 dark:text-slate-300">{t('app.tagline')}</p>
        {/* NFR-5: what leaves the browser, said before anything is typed (ADR-11.2). */}
        <p className="text-sm text-slate-500 dark:text-slate-400">{t('app.privacy')}</p>
      </div>

      {nothingHeard && (
        <p
          role="status"
          className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100"
        >
          {t('voice.empty')}
        </p>
      )}

      {phase.kind === 'input' && (
        <>
          {failure && <ErrorMessage error={failure.error} onRetry={failure.retry} />}
          <MoodInput
            value={text}
            onChange={setText}
            onSubmit={(value) => void submit(value)}
            actions={
              micAvailable && (
                <button
                  type="button"
                  onClick={() => startRecording({ kind: 'input' })}
                  className="btn-secondary"
                >
                  <span aria-hidden="true">🎤</span> {t('voice.record')}
                </button>
              )
            }
          />
          {sttEnabled && !micAvailable && !window.isSecureContext && (
            <p className="text-sm text-slate-500 dark:text-slate-400">{t('voice.insecure')}</p>
          )}
        </>
      )}

      {phase.kind === 'recording' && (
        <VoiceRecorder
          onRecorded={(recording) => void transcribeRecording(recording, phase.typedText)}
          onCancel={() => setPhase(phase.returnTo)}
        />
      )}

      {phase.kind === 'transcribing' && <ThinkingIndicator title={t('voice.transcribing')} />}

      {phase.kind === 'reviewing' && (
        <>
          {failure && <ErrorMessage error={failure.error} onRetry={failure.retry} />}
          <TranscriptReview
            value={text}
            onChange={setText}
            transcript={phase.transcript}
            onSubmit={(value) => void submit(value, phase)}
            onRecordAgain={() => startRecording(phase)}
            onDiscard={() => {
              setText(phase.typedText)
              startOver()
            }}
          />
        </>
      )}

      {phase.kind === 'thinking' && <ThinkingIndicator />}

      {phase.kind === 'clarifying' && (
        <>
          {failure && <ErrorMessage error={failure.error} />}
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
