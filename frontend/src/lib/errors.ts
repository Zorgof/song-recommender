import { ApiError } from '../api/client'
import type en from '../locales/en.json'

export type ErrorCode = Exclude<keyof typeof en.errors, 'title' | 'retry'>

const KNOWN_CODES: ReadonlySet<string> = new Set<ErrorCode>([
  'validation_error',
  'daily_limit_reached',
  'llm_unavailable',
  'llm_invalid_output',
  'catalog_unavailable',
  'stt_unavailable',
  'audio_too_large',
  'unsupported_audio_format',
  'invalid_audio',
  'not_found',
  'conflict',
  'network_error',
  'internal_error',
])

/** The error code to show a message for; unknown codes fall back to `internal_error`. */
export function errorCode(error: unknown): ErrorCode {
  if (error instanceof ApiError && KNOWN_CODES.has(error.code)) {
    return error.code as ErrorCode
  }
  return 'internal_error'
}
