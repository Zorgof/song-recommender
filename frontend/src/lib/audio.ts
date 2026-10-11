// FR-6: a voice recording is at most 90 s or 10 MB.
export const MAX_RECORDING_MS = 90_000
export const MAX_AUDIO_BYTES = 10 * 1024 * 1024

// Formats the backend accepts (backend/app/stt/base.py), in order of preference. Chrome and
// Firefox record webm/opus, Safari records mp4.
const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/mp4',
]

const EXTENSIONS: Record<string, string> = {
  'audio/webm': 'webm',
  'audio/ogg': 'ogg',
  'audio/mp4': 'mp4',
}

/**
 * Whether this browser can record here. `navigator.mediaDevices` only exists in a secure
 * context: https:// or http://localhost (NFR-4).
 */
export function canRecord(): boolean {
  return typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia
}

/** The first supported format, or undefined to let the browser choose. */
export function pickMimeType(): string | undefined {
  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type))
}

/** A file name whose extension matches the recording, e.g. `recording.webm`. */
export function recordingFilename(mimeType: string): string {
  const base = mimeType.split(';', 1)[0].trim().toLowerCase()
  return `recording.${EXTENSIONS[base] ?? 'webm'}`
}
