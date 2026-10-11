/** A date and time in the UI locale, e.g. "11 Oct 2026, 14:05" / "11 paź 2026, 14:05". */
export function formatDateTime(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(iso),
  )
}

/** Minutes and seconds, e.g. 75_000 → "1:15". */
export function formatDuration(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/** The name of a language in the UI locale, e.g. ("pl", "en") → "Polish"; null if unknown. */
export function languageName(code: string, locale: string): string | null {
  try {
    const name = new Intl.DisplayNames([locale], { type: 'language' }).of(code)
    return name && name !== code ? name : null
  } catch {
    return null
  }
}
