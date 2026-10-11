import { onTestFinished, vi } from 'vitest'

export const RECORDED_BYTES = 'fake-opus-audio'

/** A MediaRecorder that "records" RECORDED_BYTES; delivers them on stop(), like the real one. */
export class FakeMediaRecorder {
  static supportedTypes: string[] = ['audio/webm;codecs=opus', 'audio/webm']
  static instances: FakeMediaRecorder[] = []

  static isTypeSupported(type: string): boolean {
    return FakeMediaRecorder.supportedTypes.includes(type)
  }

  readonly mimeType: string
  state: 'inactive' | 'recording' = 'inactive'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null

  constructor(_stream: unknown, options?: { mimeType?: string }) {
    this.mimeType = options?.mimeType ?? 'audio/webm'
    FakeMediaRecorder.instances.push(this)
  }

  start(): void {
    this.state = 'recording'
  }

  stop(): void {
    if (this.state === 'inactive') return
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob([RECORDED_BYTES], { type: this.mimeType }) })
    this.onstop?.()
  }
}

/**
 * Give the page a microphone and MediaRecorder. `deny` makes getUserMedia fail with that
 * DOMException name (e.g. "NotAllowedError"). Removed again when the test finishes.
 */
export function installMicrophone({
  deny,
  supportedTypes = ['audio/webm;codecs=opus', 'audio/webm'],
}: { deny?: string; supportedTypes?: string[] } = {}) {
  const track = { stop: vi.fn() }
  const getUserMedia = vi.fn(async () => {
    if (deny) throw new DOMException('Permission denied', deny)
    return { getTracks: () => [track] }
  })
  FakeMediaRecorder.instances = []
  FakeMediaRecorder.supportedTypes = supportedTypes
  vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
  Object.defineProperty(navigator, 'mediaDevices', {
    value: { getUserMedia },
    configurable: true,
  })
  onTestFinished(() => {
    Reflect.deleteProperty(navigator, 'mediaDevices')
  })
  return { getUserMedia, track, recorders: FakeMediaRecorder.instances }
}
