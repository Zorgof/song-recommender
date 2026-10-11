import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { STORAGE_KEY } from '../i18n'
import { json, mockFetch, recommendation, renderApp } from '../test/utils'

describe('LanguageSwitcher', () => {
  it('switches the whole UI to Polish and remembers the choice', async () => {
    const { user } = renderApp()
    const group = screen.getByRole('group', { name: 'Language' })
    expect(screen.getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true')

    await user.click(screen.getByRole('button', { name: 'Polski' }))

    expect(group).toHaveAccessibleName('Język')
    expect(screen.getByRole('button', { name: 'Polski' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByLabelText('Jak się czujesz i jak minął Ci dzień?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Znajdź piosenkę' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Historia' })).toBeInTheDocument()
    expect(localStorage.getItem(STORAGE_KEY)).toBe('pl')
    expect(document.documentElement.lang).toBe('pl')
    expect(document.title).toBe('Song Recommender')
  })

  it('sends the selected locale, so the explanation comes back in that language', async () => {
    const calls = mockFetch(() =>
      json({
        status: 'completed',
        recommendation: recommendation({
          locale: 'pl',
          explanation: 'Spokojna piosenka na wieczór.',
        }),
      }),
    )
    const { user } = renderApp()

    await user.click(screen.getByRole('button', { name: 'Polski' }))
    // The description itself may be in any language (FR-5).
    await user.type(
      screen.getByLabelText('Jak się czujesz i jak minął Ci dzień?'),
      'A long day at work.',
    )
    await user.click(screen.getByRole('button', { name: 'Znajdź piosenkę' }))

    expect(await screen.findByText('Spokojna piosenka na wieczór.')).toBeInTheDocument()
    expect(calls[0].body).toEqual({ text: 'A long day at work.', input_mode: 'text', locale: 'pl' })
    expect(screen.getByText('Dlaczego ta piosenka')).toBeInTheDocument()
  })

  it('shows error messages in the selected language', async () => {
    mockFetch(() => Promise.reject(new TypeError('Failed to fetch')))
    const { user } = renderApp()

    await user.click(screen.getByRole('button', { name: 'Polski' }))
    await user.type(screen.getByLabelText('Jak się czujesz i jak minął Ci dzień?'), 'Zmęczony.')
    await user.click(screen.getByRole('button', { name: 'Znajdź piosenkę' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Brak połączenia z serwerem. Sprawdź, czy backend działa.',
    )
  })
})
