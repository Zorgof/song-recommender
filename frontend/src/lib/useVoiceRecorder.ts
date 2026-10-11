import { useEffect, useRef, useState } from 'react'

import { pickMimeType } from './audio'

export interface Recording {
  blob: Blob
  durationMs: number
}

export type RecorderError = 'denied' | 'noMicrophone' | 'failed'

export type RecorderState =
  | { status: 'starting' }
  | { status: 'recording'; elapsedMs: number }
  | { status: 'error'; error: RecorderError }

interface Options {
  maxMs: number
  onComplete: (recording: Recording) => void
}

const TICK_MS = 250

/**
 * Records from the microphone while the component is mounted: asks for permission, records,
 * stops at `maxMs`. `stop()` finishes the recording and calls `onComplete`; `cancel()` and
 * unmounting discard it. The microphone is released in every case.
 */
export function useVoiceRecorder({ maxMs, onComplete }: Options) {
  const [state, setState] = useState<RecorderState>({ status: 'starting' })
  const onCompleteRef = useRef(onComplete)
  const controls = useRef({ stop: () => {}, cancel: () => {} })

  useEffect(() => {
    onCompleteRef.current = onComplete
  }, [onComplete])

  useEffect(() => {
    // Set on unmount (also by React StrictMode's extra mount/unmount in development).
    let disposed = false
    let discard = false
    let stream: MediaStream | undefined
    let recorder: MediaRecorder | undefined
    let timer: ReturnType<typeof setInterval> | undefined

    const release = () => {
      clearInterval(timer)
      stream?.getTracks().forEach((track) => track.stop())
    }
    const stop = () => {
      if (recorder?.state === 'recording') recorder.stop()
      else release()
    }
    controls.current = {
      stop,
      cancel: () => {
        discard = true
        stop()
      },
    }

    async function start() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      } catch (error) {
        if (!disposed) setState({ status: 'error', error: recorderError(error) })
        return
      }
      if (disposed) {
        release()
        return
      }
      const mimeType = pickMimeType()
      try {
        recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      } catch {
        release()
        setState({ status: 'error', error: 'failed' })
        return
      }
      const chunks: Blob[] = []
      const startedAt = Date.now()
      const active = recorder
      active.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.push(event.data)
      }
      active.onstop = () => {
        release()
        if (disposed || discard) return
        const type = active.mimeType || mimeType || 'audio/webm'
        onCompleteRef.current({
          blob: new Blob(chunks, { type }),
          durationMs: Math.min(Date.now() - startedAt, maxMs),
        })
      }
      active.start()
      setState({ status: 'recording', elapsedMs: 0 })
      timer = setInterval(() => {
        const elapsedMs = Math.min(Date.now() - startedAt, maxMs)
        setState({ status: 'recording', elapsedMs })
        if (elapsedMs >= maxMs) stop()
      }, TICK_MS)
    }

    void start()
    return () => {
      disposed = true
      stop()
    }
  }, [maxMs])

  return {
    state,
    stop: () => controls.current.stop(),
    cancel: () => controls.current.cancel(),
  }
}

function recorderError(error: unknown): RecorderError {
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'denied'
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'noMicrophone'
  return 'failed'
}
