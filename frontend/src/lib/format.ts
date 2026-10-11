/** A date and time in the UI locale, e.g. "11 Oct 2026, 14:05" / "11 paź 2026, 14:05". */
export function formatDateTime(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(iso),
  )
}
