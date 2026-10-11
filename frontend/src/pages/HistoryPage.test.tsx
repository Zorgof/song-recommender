import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { HistoryItem } from '../api/types'
import { setLocale } from '../i18n'
import { apiError, historyItem, json, mockFetch, renderApp } from '../test/utils'

function page(items: HistoryItem[], total = items.length, offset = 0) {
  return json({ items, total, limit: 20, offset })
}

describe('HistoryPage', () => {
  it('lists past recommendations with their input and feedback', async () => {
    mockFetch(() =>
      page([
        historyItem({
          input_mode: 'voice',
          clarification_question: 'How do you feel?',
          clarification_answer: 'Tired.',
          feedback: { score: 'up', comment: 'Lovely', synced_to_langsmith: true },
        }),
      ]),
    )
    renderApp('/history')

    expect(await screen.findByRole('heading', { level: 3, name: 'Holocene' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'History' })).toBeInTheDocument()
    expect(screen.getByText('1 recommendation')).toBeInTheDocument()
    expect(screen.getByText('Long day, need to relax.')).toBeInTheDocument()
    expect(screen.getByText('voice')).toBeInTheDocument()
    expect(screen.getByText('How do you feel?')).toBeInTheDocument()
    expect(screen.getByText('Tired.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /It fits/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByLabelText('Comment (optional)')).toHaveValue('Lovely')
    // No embedded players in the list.
    expect(screen.queryByTitle(/Spotify player/)).not.toBeInTheDocument()
  })

  it('formats dates in the UI language', async () => {
    mockFetch(() => page([historyItem({ created_at: '2026-10-11T12:05:00+00:00' })]))
    await setLocale('pl')
    renderApp('/history')

    const time = await screen.findByText((_, element) => element?.tagName === 'TIME')
    expect(time).toHaveAttribute('dateTime', '2026-10-11T12:05:00+00:00')
    const expected = new Intl.DateTimeFormat('pl', { dateStyle: 'medium', timeStyle: 'short' })
    expect(time).toHaveTextContent(expected.format(new Date('2026-10-11T12:05:00+00:00')))
    expect(screen.getByText('1 rekomendacja')).toBeInTheDocument()
  })

  it('pages through the history', async () => {
    const calls = mockFetch(({ path }) => {
      const offset = Number(new URLSearchParams(path.split('?')[1]).get('offset'))
      return page(
        [historyItem({ request_id: `req-${offset}`, title: `Song ${offset}` })],
        45,
        offset,
      )
    })
    const { user } = renderApp('/history')

    expect(await screen.findByText('Page 1 of 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(await screen.findByRole('heading', { name: 'Song 20' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(await screen.findByRole('heading', { name: 'Song 40' })).toBeInTheDocument()

    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    expect(calls.map((call) => call.path)).toEqual([
      '/recommendations?limit=20&offset=0',
      '/recommendations?limit=20&offset=20',
      '/recommendations?limit=20&offset=40',
    ])
  })

  it('opens the page from the URL', async () => {
    const calls = mockFetch(() => page([historyItem()], 45, 20))
    renderApp('/history?page=2')

    expect(await screen.findByText('Page 2 of 3')).toBeInTheDocument()
    expect(calls[0].path).toBe('/recommendations?limit=20&offset=20')
  })

  it('shows an empty state', async () => {
    mockFetch(() => page([]))
    renderApp('/history')

    expect(await screen.findByText('No recommendations yet.')).toBeInTheDocument()
  })

  it('shows an error with a retry', async () => {
    let fail = true
    mockFetch(() => (fail ? apiError('internal_error', 500) : page([historyItem()])))
    const { user } = renderApp('/history')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('An unexpected error occurred.')
    fail = false
    await user.click(within(alert).getByRole('button', { name: 'Try again' }))

    expect(await screen.findByRole('heading', { name: 'Holocene' })).toBeInTheDocument()
  })

  it('is reachable from the navigation', async () => {
    mockFetch(() => page([]))
    const { user } = renderApp('/')

    await user.click(screen.getByRole('link', { name: 'History' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'History' })).toBeInTheDocument()
  })
})
