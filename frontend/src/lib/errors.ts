import { ApiError } from '../api/client'
import type en from '../locales/en.json'

export type ErrorCode = Exclude<keyof typeof en.errors, 'title' | 'retry'>

const KNOWN_CODES: ReadonlySet<string> = new Set<ErrorCode>([
  'validation_error',
  'daily_limit_reached',
  'daily_capacity_reached',
  'budget_exhausted',
  'rate_limited',
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

// Limits and the spent budget: trying again the same day cannot help (ADR-11.1, ADR-11.2).
const FINAL_CODES: ReadonlySet<ErrorCode> = new Set<ErrorCode>([
  'daily_limit_reached',
  'daily_capacity_reached',
  'budget_exhausted',
])

/** Whether "Try again" can help with this error. */
export function canRetry(error: unknown): boolean {
  return !FINAL_CODES.has(errorCode(error))
}

/** The error code to show a message for; unknown codes fall back to `internal_error`. */
export function errorCode(error: unknown): ErrorCode {
  if (error instanceof ApiError && KNOWN_CODES.has(error.code)) {
    return error.code as ErrorCode
  }
  return 'internal_error'
}
