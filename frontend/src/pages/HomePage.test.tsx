import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { RecommendationResponse } from '../api/types'
import { apiError, json, mockFetch, recommendation, renderApp } from '../test/utils'

const DESCRIPTION = 'A long, tiring day. I want to slow down.'

const completed = (overrides = {}): RecommendationResponse => ({
  status: 'completed',
  recommendation: recommendation(overrides),
})

async function describeDay(user: ReturnType<typeof renderApp>['user'], text = DESCRIPTION) {
  await user.type(screen.getByLabelText('How are you, and how was your day?'), text)
  await user.click(screen.getByRole('button', { name: 'Find my song' }))
}

describe('HomePage', () => {
  it('recommends a song for a text description', async () => {
    const calls = mockFetch(() => json(completed()))
    const { user } = renderApp()

    await describeDay(user, `  ${DESCRIPTION}  `)

    expect(await screen.findByRole('heading', { name: 'Holocene' })).toBeInTheDocument()
    expect(calls).toEqual([
      {
        method: 'POST',
        path: '/recommendations',
        body: { text: DESCRIPTION, input_mode: 'text', locale: 'en' },
      },
    ])
    expect(screen.getByRole('button', { name: /It fits/ })).toBeInTheDocument()
  })

  it('shows a progress status while the agents work', async () => {
    let finish: (response: Response) => void = () => {}
    mockFetch(() => new Promise<Response>((resolve) => (finish = resolve)))
    const { user } = renderApp()

    await describeDay(user)

    expect(screen.getByRole('status')).toHaveTextContent('Finding your song…')
    finish(json(completed()))
    expect(await screen.findByRole('heading', { name: 'Holocene' })).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('asks the clarifying question and resumes with the answer', async () => {
    const calls = mockFetch(({ path }) =>
      path === '/recommendations'
        ? json({ status: 'needs_clarification', request_id: 'req-9', question: 'How do you feel?' })
        : json(completed({ request_id: 'req-9' })),
    )
    const { user } = renderApp()

    await describeDay(user, 'meh')
    expect(await screen.findByText('How do you feel?')).toBeInTheDocument()
    const answer = screen.getByLabelText('Your answer')
    expect(answer).toHaveFocus()
    await user.type(answer, '  Tired but calm.  ')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByRole('heading', { name: 'Holocene' })).toBeInTheDocument()
    expect(calls[1]).toEqual({
      method: 'POST',
      path: '/recommendations/req-9/clarification',
      body: { answer: 'Tired but calm.' },
    })
  })

  it('can start over from the clarifying question, keeping the text', async () => {
    mockFetch(() =>
      json({ status: 'needs_clarification', request_id: 'req-9', question: 'How do you feel?' }),
    )
    const { user } = renderApp()

    await describeDay(user, 'meh')
    await user.click(await screen.findByRole('button', { name: 'Start over' }))

    expect(screen.getByLabelText('How are you, and how was your day?')).toHaveValue('meh')
  })

  it('does not send a description under 3 characters', async () => {
    const calls = mockFetch(() => json(completed()))
    const { user } = renderApp()

    await describeDay(user, ' a ')

    expect(screen.getByRole('alert')).toHaveTextContent('Write at least 3 characters.')
    expect(calls).toEqual([])
  })

  it('submits with Ctrl+Enter', async () => {
    const calls = mockFetch(() => json(completed()))
    const { user } = renderApp()

    await user.type(screen.getByLabelText('How are you, and how was your day?'), DESCRIPTION)
    await user.keyboard('{Control>}{Enter}{/Control}')

    await waitFor(() => expect(calls).toHaveLength(1))
  })

  it('shows a localized error, keeps the text and retries', async () => {
    let fail = true
    const calls = mockFetch(() => (fail ? apiError('llm_unavailable', 503) : json(completed())))
    const { user } = renderApp()

    await describeDay(user)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The language model is unavailable right now.',
    )
    expect(screen.getByLabelText('How are you, and how was your day?')).toHaveValue(DESCRIPTION)
    fail = false
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { name: 'Holocene' })).toBeInTheDocument()
    expect(calls).toHaveLength(2)
  })

  it('explains the daily limit', async () => {
    mockFetch(() => apiError('daily_limit_reached', 429))
    const { user } = renderApp()

    await describeDay(user)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "You have used today's limit for this test version.",
    )
  })

  it('keeps the question after a failed answer, but not after a conflict', async () => {
    const answers = [apiError('catalog_unavailable', 503), apiError('conflict', 409)]
    mockFetch(({ path }) =>
      path === '/recommendations'
        ? json({ status: 'needs_clarification', request_id: 'req-9', question: 'How do you feel?' })
        : answers.shift()!,
    )
    const { user } = renderApp()
    await describeDay(user, 'meh')

    await user.type(await screen.findByLabelText('Your answer'), 'Fine.')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Spotify is unavailable right now')
    expect(screen.getByText('How do you feel?')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Your answer'), 'Fine.')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Please start over.')
    expect(screen.queryByText('How do you feel?')).not.toBeInTheDocument()
    expect(screen.getByLabelText('How are you, and how was your day?')).toHaveValue('meh')
  })

  it('starts a new description after a result', async () => {
    mockFetch(() => json(completed()))
    const { user } = renderApp()
    await describeDay(user)

    await user.click(await screen.findByRole('button', { name: 'Describe another moment' }))

    expect(screen.getByLabelText('How are you, and how was your day?')).toHaveValue('')
  })
})
