// Mirrors the backend schemas (backend/app/api/*_schemas.py, backend/app/agents/schemas.py).

export const LOCALES = ['en', 'pl'] as const
export type Locale = (typeof LOCALES)[number]
export type InputMode = 'text' | 'voice'
export type Score = 'up' | 'down'

export interface Recommendation {
  request_id: string
  locale: Locale
  title: string
  artist: string
  album_art_url: string | null
  // A track URL when verified, otherwise a Spotify search URL.
  spotify_url: string
  spotify_track_id: string | null
  // A video URL when verified, otherwise a YouTube search URL.
  youtube_url: string
  spotify_verified: boolean
  youtube_verified: boolean
  // In the UI locale of the request.
  explanation: string
  need_summary: string
  // Null when LangSmith tracing is off.
  trace_url: string | null
}

export interface CompletedResponse {
  status: 'completed'
  recommendation: Recommendation
}

export interface NeedsClarificationResponse {
  status: 'needs_clarification'
  request_id: string
  question: string
}

export type RecommendationResponse = CompletedResponse | NeedsClarificationResponse

export interface RecommendationRequest {
  text: string
  input_mode: InputMode
  locale: Locale
  // Voice input only: the raw transcript before the user's edits.
  transcript?: string
}

export interface FeedbackRequest {
  score: Score
  comment?: string
}

export interface FeedbackOut {
  score: Score
  comment: string | null
  synced_to_langsmith: boolean
}

export interface HistoryItem {
  request_id: string
  // ISO 8601, UTC.
  created_at: string
  locale: string
  input_mode: InputMode
  input_text: string
  clarification_question: string | null
  clarification_answer: string | null
  title: string | null
  artist: string | null
  album_art_url: string | null
  spotify_url: string | null
  spotify_track_id: string | null
  spotify_verified: boolean
  youtube_url: string | null
  youtube_verified: boolean
  explanation: string | null
  need_summary: string | null
  trace_url: string | null
  feedback: FeedbackOut | null
}

export interface HistoryPage {
  items: HistoryItem[]
  total: number
  limit: number
  offset: number
}

export interface ErrorBody {
  error: { code: string; message: string; details?: unknown }
}
