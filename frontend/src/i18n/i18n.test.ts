import { afterEach, describe, expect, it, vi } from 'vitest'

import en from '../locales/en.json'
import pl from '../locales/pl.json'
import i18n, { STORAGE_KEY, currentLocale, detectLocale, setLocale } from '.'

// i18next plural suffixes; Polish needs more forms than English.
const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/

function keys(object: object, prefix = ''): string[] {
  return Object.entries(object).flatMap(([key, value]) =>
    typeof value === 'object' && value !== null
      ? keys(value, `${prefix}${key}.`)
      : [`${prefix}${key}`.replace(PLURAL_SUFFIX, '')],
  )
}

function placeholders(object: object): Record<string, string[]> {
  const result: Record<string, string[]> = {}
  const walk = (value: unknown, path: string) => {
    if (typeof value === 'string') {
      result[path.replace(PLURAL_SUFFIX, '')] = [...value.matchAll(/{{(\w+)}}/g)]
        .map((m) => m[1])
        .sort()
    } else if (typeof value === 'object' && value !== null) {
      for (const [k, v] of Object.entries(value)) walk(v, path ? `${path}.${k}` : k)
    }
  }
  walk(object, '')
  return result
}

describe('translations', () => {
  it('have the same keys in English and Polish', () => {
    expect(new Set(keys(pl))).toEqual(new Set(keys(en)))
  })

  it('use the same placeholders in both languages', () => {
    expect(placeholders(pl)).toEqual(placeholders(en))
  })

  it('cover every Polish plural form', () => {
    expect(Object.keys(pl.history)).toEqual(
      expect.arrayContaining(['count_one', 'count_few', 'count_many', 'count_other']),
    )
    expect(i18n.t('history.count', { count: 2, lng: 'pl' })).toBe('2 rekomendacje')
    expect(i18n.t('history.count', { count: 5, lng: 'pl' })).toBe('5 rekomendacji')
    expect(i18n.t('history.count', { count: 1, lng: 'en' })).toBe('1 recommendation')
  })
})

describe('detectLocale', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  function browserLanguages(...languages: string[]) {
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(languages)
  }

  it('prefers the stored choice', () => {
    browserLanguages('en-US')
    localStorage.setItem(STORAGE_KEY, 'pl')
    expect(detectLocale()).toBe('pl')
  })

  it('follows the first supported browser language', () => {
    browserLanguages('de-DE', 'pl-PL', 'en')
    expect(detectLocale()).toBe('pl')
  })

  it('falls back to English', () => {
    browserLanguages('de-DE', 'fr')
    expect(detectLocale()).toBe('en')
  })

  it('ignores an invalid stored value', () => {
    browserLanguages('pl')
    localStorage.setItem(STORAGE_KEY, 'xx')
    expect(detectLocale()).toBe('pl')
  })

  it('works when storage is blocked', async () => {
    browserLanguages('pl')
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })

    expect(detectLocale()).toBe('pl')
    await setLocale('en')
    expect(currentLocale()).toBe('en')
  })
})

describe('setLocale', () => {
  it('switches the language, remembers it and updates <html lang>', async () => {
    await setLocale('pl')

    expect(currentLocale()).toBe('pl')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('pl')
    expect(document.documentElement.lang).toBe('pl')
  })
})
