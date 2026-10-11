import { useTranslation } from 'react-i18next'

import { MAX_RECORDING_MS } from '../lib/audio'
import { formatDuration } from '../lib/format'
import { useVoiceRecorder, type Recording } from '../lib/useVoiceRecorder'

interface Props {
  onRecorded: (recording: Recording) => void
  onCancel: () => void
  maxMs?: number
}

/** Records while mounted; "Stop" (or the time limit) hands the recording over. */
export function VoiceRecorder({ onRecorded, onCancel, maxMs = MAX_RECORDING_MS }: Props) {
  const { t } = useTranslation()
  const recorder = useVoiceRecorder({ maxMs, onComplete: onRecorded })
  const { state } = recorder
  const max = formatDuration(maxMs)

  if (state.status === 'error') {
    return (
      <div
        role="alert"
        className="space-y-3 rounded-lg border border-red-300 bg-red-50 p-4 text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100"
      >
        <p>{t(`voice.${state.error}`)}</p>
        <button type="button" onClick={onCancel} className="btn-secondary">
          {t('voice.back')}
        </button>
      </div>
    )
  }

  const cancel = () => {
    recorder.cancel()
    onCancel()
  }

  return (
    <div className="space-y-4 rounded-lg bg-white p-6 shadow-sm dark:bg-slate-800">
      {state.status === 'starting' ? (
        <div role="status">
          <p className="font-semibold">{t('voice.starting')}</p>
          <p className="text-sm text-slate-600 dark:text-slate-300">{t('voice.permissionHint')}</p>
        </div>
      ) : (
        <div className="space-y-1">
          <p className="flex items-center gap-3 font-semibold">
            <span aria-hidden="true" className="size-3 animate-pulse rounded-full bg-red-600" />
            <span role="status">{t('voice.recording')}</span>
            <span role="timer" className="font-mono tabular-nums">
              {t('voice.timer', { elapsed: formatDuration(state.elapsedMs), max })}
            </span>
          </p>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            {t('voice.limitHint', { max })}
          </p>
        </div>
      )}
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={recorder.stop}
          disabled={state.status !== 'recording'}
          className="btn-primary"
        >
          {t('voice.stop')}
        </button>
        <button type="button" onClick={cancel} className="btn-secondary">
          {t('voice.cancel')}
        </button>
      </div>
    </div>
  )
}
