import { describe, expect, it, vi } from 'vitest'

import { apiError, json, mockFetch } from '../test/utils'
import { ApiError, api } from './client'

describe('api client', () => {
  it('posts JSON and returns the parsed body', async () => {
    const calls = mockFetch(() =>
      json({ status: 'needs_clarification', request_id: 'r', question: 'q' }),
    )

    const response = await api.recommend({ text: 'Long day.', input_mode: 'text', locale: 'pl' })

    expect(response).toEqual({ status: 'needs_clarification', request_id: 'r', question: 'q' })
    expect(calls).toEqual([
      {
        method: 'POST',
        path: '/recommendations',
        body: { text: 'Long day.', input_mode: 'text', locale: 'pl' },
      },
    ])
  })

  it('returns undefined for 204 No Content and escapes ids', async () => {
    const calls = mockFetch(() => new Response(null, { status: 204 }))

    await expect(api.sendFeedback('a/b', { score: 'up' })).resolves.toBeUndefined()
    expect(calls[0].path).toBe('/recommendations/a%2Fb/feedback')
  })

  it('builds the history query', async () => {
    const calls = mockFetch(() => json({ items: [], total: 0, limit: 20, offset: 40 }))

    await api.history(20, 40)

    expect(calls[0].path).toBe('/recommendations?limit=20&offset=40')
  })

  it('turns the backend error shape into an ApiError', async () => {
    mockFetch(() => apiError('llm_unavailable', 503))

    const error = await api.history(20, 0).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ code: 'llm_unavailable', status: 503 })
  })

  it('maps a non-JSON error response to internal_error', async () => {
    mockFetch(() => new Response('<html>Bad Gateway</html>', { status: 502 }))

    await expect(api.history(20, 0)).rejects.toMatchObject({ code: 'internal_error', status: 502 })
  })

  it('maps a failed request to network_error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await expect(api.history(20, 0)).rejects.toMatchObject({ code: 'network_error', status: 0 })
  })
})
