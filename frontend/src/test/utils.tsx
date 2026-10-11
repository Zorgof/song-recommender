import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import App from '../App'
import type { HistoryItem, Recommendation } from '../api/types'

export function renderWithProviders(ui: ReactElement, { route = '/' } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const user = userEvent.setup()
  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
  return { user, queryClient, ...result }
}

export function renderApp(route = '/') {
  return renderWithProviders(<App />, { route })
}

// --- fetch ---

export interface Call {
  method: string
  path: string
  body: unknown
}

type Handler = (call: Call) => Response | Promise<Response>

/** Replace fetch; `calls` records every request (path relative to /api, parsed JSON body). */
export function mockFetch(handler: Handler) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const call: Call = {
      method: init?.method ?? 'GET',
      path: url.pathname.replace(/^\/api/, '') + url.search,
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    }
    calls.push(call)
    return handler(call)
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

export function apiError(code: string, status: number): Response {
  return json({ error: { code, message: `backend message for ${code}` } }, status)
}

// --- fixtures ---

export function recommendation(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    request_id: 'req-1',
    locale: 'en',
    title: 'Holocene',
    artist: 'Bon Iver',
    album_art_url: 'https://i.scdn.co/image/holocene',
    spotify_url: 'https://open.spotify.com/track/4fbvXwMTXPWaFyaMWUm9CR',
    spotify_track_id: '4fbvXwMTXPWaFyaMWUm9CR',
    youtube_url: 'https://www.youtube.com/watch?v=TWcyIpul8OE',
    spotify_verified: true,
    youtube_verified: true,
    explanation: 'A slow, warm song to help you unwind.',
    need_summary: 'You are tired and want to relax.',
    trace_url: null,
    ...overrides,
  }
}

export function historyItem(overrides: Partial<HistoryItem> = {}): HistoryItem {
  const { locale: _locale, ...song } = recommendation()
  return {
    ...song,
    created_at: '2026-10-11T12:05:00+00:00',
    locale: 'en',
    input_mode: 'text',
    input_text: 'Long day, need to relax.',
    clarification_question: null,
    clarification_answer: null,
    feedback: null,
    ...overrides,
  }
}
