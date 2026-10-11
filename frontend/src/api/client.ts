import type {
  FeedbackRequest,
  HistoryPage,
  RecommendationRequest,
  RecommendationResponse,
} from './types'

const BASE = '/api'

// Codes produced by the client itself, next to the backend's codes (implementation plan, 2.6).
export const NETWORK_ERROR = 'network_error'
const UNKNOWN_ERROR = 'internal_error'

/** An error with the backend's stable `code`; the UI maps it to a localized message. */
export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(BASE + path, {
      ...init,
      headers: { Accept: 'application/json', ...init?.headers },
    })
  } catch (error) {
    throw new ApiError(NETWORK_ERROR, String(error), 0)
  }
  if (!response.ok) {
    throw await toApiError(response)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body: unknown = await response.json()
    if (isErrorBody(body)) {
      return new ApiError(body.error.code, body.error.message, response.status)
    }
  } catch {
    // Not JSON, e.g. an HTML error page from a proxy.
  }
  return new ApiError(UNKNOWN_ERROR, response.statusText, response.status)
}

function isErrorBody(body: unknown): body is { error: { code: string; message: string } } {
  if (typeof body !== 'object' || body === null || !('error' in body)) return false
  const error = body.error
  return (
    typeof error === 'object' &&
    error !== null &&
    'code' in error &&
    typeof error.code === 'string' &&
    'message' in error &&
    typeof error.message === 'string'
  )
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export const api = {
  recommend: (body: RecommendationRequest) =>
    postJson<RecommendationResponse>('/recommendations', body),

  answerClarification: (requestId: string, answer: string) =>
    postJson<RecommendationResponse>(
      `/recommendations/${encodeURIComponent(requestId)}/clarification`,
      { answer },
    ),

  sendFeedback: (requestId: string, body: FeedbackRequest) =>
    postJson<void>(`/recommendations/${encodeURIComponent(requestId)}/feedback`, body),

  history: (limit: number, offset: number) =>
    request<HistoryPage>(
      `/recommendations?${new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      })}`,
    ),
}
