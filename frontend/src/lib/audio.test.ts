import { describe, expect, it, vi } from 'vitest'

import { installMicrophone } from '../test/fakeMedia'
import { canRecord, pickMimeType, recordingFilename } from './audio'

describe('audio helpers', () => {
  it('prefers webm/opus, then falls back to what the browser records', () => {
    installMicrophone({ supportedTypes: ['audio/webm;codecs=opus', 'audio/mp4'] })
    expect(pickMimeType()).toBe('audio/webm;codecs=opus')

    installMicrophone({ supportedTypes: ['audio/ogg;codecs=opus'] })
    expect(pickMimeType()).toBe('audio/ogg;codecs=opus')

    installMicrophone({ supportedTypes: [] })
    expect(pickMimeType()).toBeUndefined()
  })

  it('names the upload after its format', () => {
    expect(recordingFilename('audio/webm;codecs=opus')).toBe('recording.webm')
    expect(recordingFilename('audio/ogg; codecs=opus')).toBe('recording.ogg')
    expect(recordingFilename('audio/mp4')).toBe('recording.mp4')
    expect(recordingFilename('')).toBe('recording.webm')
  })

  it('can record only with MediaRecorder and a microphone API', () => {
    expect(canRecord()).toBe(false)
    installMicrophone()
    expect(canRecord()).toBe(true)
    vi.unstubAllGlobals()
    expect(canRecord()).toBe(false)
  })
})
