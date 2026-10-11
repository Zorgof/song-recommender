import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import App from '../App'
import type { HistoryItem, Meta, Recommendation } from '../api/types'

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
  // Parsed JSON body.
  body: unknown
  // Multipart body (uploads).
  form?: FormData
}

type Handler = (call: Call) => Response | Promise<Response>

export function meta(sttEnabled = false): Meta {
  return {
    app: { name: 'song-recommender', version: '0.1.0', environment: 'development' },
    llm: {
      light: 'openai:light',
      heavy: 'openai:heavy',
      light_fallback: null,
      heavy_fallback: null,
      heavy_reasoning: false,
    },
    stt: {
      enabled: sttEnabled,
      provider: sttEnabled ? 'openai' : 'none',
      model: sttEnabled ? 'gpt-transcribe' : null,
    },
    catalogs: { spotify: true, youtube: true },
    langsmith: { enabled: false, project: null },
    locales: ['en', 'pl'],
  }
}

/**
 * Replace fetch; `calls` records every request (path relative to /api, parsed body).
 * `GET /api/meta` is answered automatically (STT off unless `sttEnabled`) and not recorded.
 */
export function mockFetch(handler: Handler, { sttEnabled = false } = {}) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const path = url.pathname.replace(/^\/api/, '') + url.search
    if (path === '/meta') return json(meta(sttEnabled))
    const call: Call = {
      method: init?.method ?? 'GET',
      path,
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    }
    if (init?.body instanceof FormData) call.form = init.body
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
