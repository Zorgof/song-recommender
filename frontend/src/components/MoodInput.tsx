import { useId, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

// FR-6: 3-2000 characters, counted after trimming (as the backend does).
export const MIN_TEXT = 3
export const MAX_TEXT = 2000

interface Props {
  value: string
  onChange: (value: string) => void
  onSubmit: (text: string) => void
  // Defaults: the "How are you…" label and the "write in any language" hint.
  label?: string
  hint?: ReactNode
  // Extra buttons next to "Find my song" (record, record again, discard).
  actions?: ReactNode
  autoFocus?: boolean
}

export function MoodInput({
  value,
  onChange,
  onSubmit,
  label,
  hint,
  actions,
  autoFocus = false,
}: Props) {
  const { t } = useTranslation()
  const id = useId()
  const [showTooShort, setShowTooShort] = useState(false)
  const length = value.trim().length
  const tooShort = length < MIN_TEXT

  function submit(event: FormEvent) {
    event.preventDefault()
    if (tooShort) {
      setShowTooShort(true)
      return
    }
    onSubmit(value.trim())
  }

  function submitOnCtrlEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <label htmlFor={id} className="block text-lg font-semibold">
        {label ?? t('input.label')}
      </label>
      <textarea
        id={id}
        value={value}
        onChange={(event) => {
          onChange(event.target.value)
          setShowTooShort(false)
        }}
        onKeyDown={submitOnCtrlEnter}
        placeholder={t('input.placeholder')}
        maxLength={MAX_TEXT}
        rows={5}
        autoFocus={autoFocus}
        aria-describedby={`${id}-hint`}
        aria-invalid={showTooShort}
        className="field"
      />
      <div className="flex justify-between gap-4 text-sm text-slate-500 dark:text-slate-400">
        <span id={`${id}-hint`}>{hint ?? t('input.hint')}</span>
        <span aria-hidden="true">{t('input.counter', { count: value.length, max: MAX_TEXT })}</span>
      </div>
      {showTooShort && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-400">
          {t('input.tooShort', { min: MIN_TEXT })}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" className="btn-primary">
          {t('input.submit')}
        </button>
        {actions}
      </div>
    </form>
  )
}
