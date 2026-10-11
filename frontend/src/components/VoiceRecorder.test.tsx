import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { installMicrophone } from '../test/fakeMedia'
import { VoiceRecorder } from './VoiceRecorder'

// Lets the getUserMedia promise resolve.
const flush = () => act(async () => {})

describe('VoiceRecorder', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('counts the time and stops by itself at 90 seconds (FR-6)', async () => {
    const mic = installMicrophone()
    const onRecorded = vi.fn()
    render(<VoiceRecorder onRecorded={onRecorded} onCancel={() => {}} />)
    await flush()

    act(() => vi.advanceTimersByTime(75_000))
    expect(screen.getByRole('timer')).toHaveTextContent('1:15 / 1:30')
    expect(onRecorded).not.toHaveBeenCalled()

    act(() => vi.advanceTimersByTime(15_000))
    expect(onRecorded).toHaveBeenCalledTimes(1)
    expect(onRecorded.mock.calls[0][0]).toMatchObject({ durationMs: 90_000 })
    expect(onRecorded.mock.calls[0][0].blob.type).toBe('audio/webm;codecs=opus')
    expect(mic.track.stop).toHaveBeenCalled()
  })

  it('stops on request', async () => {
    installMicrophone()
    const onRecorded = vi.fn()
    render(<VoiceRecorder onRecorded={onRecorded} onCancel={() => {}} />)
    expect(screen.getByRole('button', { name: 'Stop and transcribe' })).toBeDisabled()
    await flush()

    act(() => vi.advanceTimersByTime(3_000))
    fireEvent.click(screen.getByRole('button', { name: 'Stop and transcribe' }))

    expect(onRecorded).toHaveBeenCalledWith(expect.objectContaining({ durationMs: 3_000 }))
  })

  it('releases the microphone and discards the recording when unmounted', async () => {
    const mic = installMicrophone()
    const onRecorded = vi.fn()
    const { unmount } = render(<VoiceRecorder onRecorded={onRecorded} onCancel={() => {}} />)
    await flush()

    unmount()

    // At once, not when the time limit would have been reached.
    expect(mic.track.stop).toHaveBeenCalled()
    expect(mic.recorders[0].state).toBe('inactive')
    act(() => vi.advanceTimersByTime(90_000))
    expect(onRecorded).not.toHaveBeenCalled()
  })

  it('releases a microphone granted after unmounting', async () => {
    const mic = installMicrophone()
    const { unmount } = render(<VoiceRecorder onRecorded={() => {}} onCancel={() => {}} />)

    unmount()
    await flush()

    expect(mic.track.stop).toHaveBeenCalled()
    expect(mic.recorders).toHaveLength(0)
  })

  it('asks for permission first', () => {
    installMicrophone()
    render(<VoiceRecorder onRecorded={() => {}} onCancel={() => {}} />)

    expect(screen.getByRole('status')).toHaveTextContent('Waiting for the microphone…')
  })
})
