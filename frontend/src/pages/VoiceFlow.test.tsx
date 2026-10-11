import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Transcription } from '../api/types'
import { RECORDED_BYTES, installMicrophone } from '../test/fakeMedia'
import { apiError, json, mockFetch, recommendation, renderApp, type Call } from '../test/utils'

const RAW = 'Miałem dziś ciężki dzień w pracy, chcę się wyciszyć.'
const TRANSCRIPT: Transcription = { text: RAW, language: 'pl', duration_s: 4 }
const INPUT_LABEL = 'How are you, and how was your day?'

function backend(transcripts: (Transcription | Response)[] = [TRANSCRIPT]) {
  return mockFetch(
    ({ path }: Call) => {
      if (path === '/transcriptions') {
        const next = transcripts.shift()!
        return next instanceof Response ? next : json(next)
      }
      return json({ status: 'completed', recommendation: recommendation() })
    },
    { sttEnabled: true },
  )
}

async function record(user: ReturnType<typeof renderApp>['user']) {
  await user.click(await screen.findByRole('button', { name: 'Record' }))
  await screen.findByRole('timer')
  await user.click(screen.getByRole('button', { name: 'Stop and transcribe' }))
}

describe('voice input', () => {
  it('records, shows the editable transcript and sends it as voice input', async () => {
    const mic = installMicrophone()
    const calls = backend()
    const { user } = renderApp()

    await user.click(await screen.findByRole('button', { name: 'Record' }))
    expect(await screen.findByRole('timer')).toHaveTextContent('0:00 / 1:30')
    expect(screen.getByText('Recording')).toBeInTheDocument()
    expect(mic.getUserMedia).toHaveBeenCalledWith({ audio: true })
    await user.click(screen.getByRole('button', { name: 'Stop and transcribe' }))

    // FR-3: the transcript is shown for editing before anything is sent.
    const review = await screen.findByLabelText('Check the transcript')
    expect(review).toHaveValue(RAW)
    expect(review).toHaveFocus()
    expect(screen.getByText(/Detected language: Polish/)).toBeInTheDocument()
    expect(mic.track.stop).toHaveBeenCalled()

    const upload = calls[0]
    expect(upload).toMatchObject({ method: 'POST', path: '/transcriptions' })
    const audio = upload.form!.get('audio') as File
    expect(audio.name).toBe('recording.webm')
    expect(audio.type).toBe('audio/webm;codecs=opus')
    expect(await audio.text()).toBe(RECORDED_BYTES)

    await user.type(review, ' Coś instrumentalnego.')
    await user.click(screen.getByRole('button', { name: 'Find my song' }))

    expect(await screen.findByRole('heading', { name: 'Holocene' })).toBeInTheDocument()
    expect(calls[1]).toEqual({
      method: 'POST',
      path: '/recommendations',
      body: {
        text: `${RAW} Coś instrumentalnego.`,
        input_mode: 'voice',
        locale: 'en',
        transcript: RAW,
      },
    })
  })

  it('uses the format the browser supports, e.g. mp4 in Safari', async () => {
    installMicrophone({ supportedTypes: ['audio/mp4'] })
    const calls = backend()
    const { user } = renderApp()

    await record(user)

    await screen.findByLabelText('Check the transcript')
    const audio = calls[0].form!.get('audio') as File
    expect([audio.name, audio.type]).toEqual(['recording.mp4', 'audio/mp4'])
  })

  it('hides the microphone when speech-to-text is disabled', async () => {
    installMicrophone()
    mockFetch(() => json({}), { sttEnabled: false })
    const { queryClient } = renderApp()

    await waitFor(() => expect(queryClient.getQueryState(['meta'])?.status).toBe('success'))
    expect(screen.queryByRole('button', { name: 'Record' })).not.toBeInTheDocument()
    expect(screen.getByLabelText(INPUT_LABEL)).toBeInTheDocument()
  })

  it('explains that the microphone needs a secure context', async () => {
    // No MediaRecorder / mediaDevices: what a browser exposes on plain http from the LAN.
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true })
    backend()
    renderApp()

    expect(await screen.findByText(/Voice input needs a secure connection/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Record' })).not.toBeInTheDocument()
    Reflect.deleteProperty(window, 'isSecureContext')
  })

  it('explains a blocked microphone and goes back to typing', async () => {
    installMicrophone({ deny: 'NotAllowedError' })
    const calls = backend()
    const { user } = renderApp()
    await user.type(await screen.findByLabelText(INPUT_LABEL), 'typed first')

    await user.click(await screen.findByRole('button', { name: 'Record' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Microphone access is blocked.')
    await user.click(screen.getByRole('button', { name: 'Back to typing' }))
    expect(screen.getByLabelText(INPUT_LABEL)).toHaveValue('typed first')
    expect(calls).toEqual([])
  })

  it('reports a missing microphone', async () => {
    installMicrophone({ deny: 'NotFoundError' })
    backend()
    const { user } = renderApp()

    await user.click(await screen.findByRole('button', { name: 'Record' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('No microphone was found.')
  })

  it('cancels a recording without sending it', async () => {
    const mic = installMicrophone()
    const calls = backend()
    const { user } = renderApp()
    await user.type(await screen.findByLabelText(INPUT_LABEL), 'typed first')

    await user.click(screen.getByRole('button', { name: 'Record' }))
    await screen.findByRole('timer')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.getByLabelText(INPUT_LABEL)).toHaveValue('typed first')
    expect(mic.track.stop).toHaveBeenCalled()
    expect(calls).toEqual([])
  })

  it('says so when no speech was recognized and restores the typed text', async () => {
    installMicrophone()
    backend([{ text: '  ', language: null, duration_s: 2 }])
    const { user } = renderApp()
    await user.type(await screen.findByLabelText(INPUT_LABEL), 'typed first')

    await record(user)

    expect(await screen.findByText(/We didn't catch any speech/)).toBeInTheDocument()
    expect(screen.getByLabelText(INPUT_LABEL)).toHaveValue('typed first')
  })

  it('retries a failed transcription with the same recording', async () => {
    installMicrophone()
    const calls = backend([apiError('stt_unavailable', 503), TRANSCRIPT])
    const { user } = renderApp()

    await record(user)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Speech recognition is unavailable right now.',
    )
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByLabelText('Check the transcript')).toHaveValue(RAW)
    expect(calls.map((call) => call.path)).toEqual(['/transcriptions', '/transcriptions'])
    const [first, second] = calls.map((call) => call.form!.get('audio') as File)
    expect(await second.text()).toBe(await first.text())
  })

  it('offers no retry when the recording itself was rejected', async () => {
    installMicrophone()
    backend([apiError('invalid_audio', 422)])
    const { user } = renderApp()

    await record(user)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The recording could not be processed.',
    )
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })

  it('records again or discards from the review', async () => {
    installMicrophone()
    const second = { text: 'Second take.', language: 'en', duration_s: 2 }
    backend([TRANSCRIPT, second])
    const { user } = renderApp()
    await user.type(await screen.findByLabelText(INPUT_LABEL), 'typed first')

    await record(user)
    await screen.findByLabelText('Check the transcript')
    await user.click(screen.getByRole('button', { name: 'Record again' }))
    await screen.findByRole('timer')
    await user.click(screen.getByRole('button', { name: 'Stop and transcribe' }))
    expect(await screen.findByLabelText('Check the transcript')).toHaveValue('Second take.')
    expect(screen.getByText(/Detected language: English/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Discard' }))
    expect(screen.getByLabelText(INPUT_LABEL)).toHaveValue('typed first')
  })

  it('keeps the edited transcript when sending fails, and retries as voice', async () => {
    installMicrophone()
    let fail = true
    const calls = mockFetch(
      ({ path }) => {
        if (path === '/transcriptions') return json(TRANSCRIPT)
        if (fail) return apiError('llm_unavailable', 503)
        return json({ status: 'completed', recommendation: recommendation() })
      },
      { sttEnabled: true },
    )
    const { user } = renderApp()
    await record(user)
    await user.type(await screen.findByLabelText('Check the transcript'), ' Edited.')
    await user.click(screen.getByRole('button', { name: 'Find my song' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('The language model is unavailable')
    expect(screen.getByLabelText('Check the transcript')).toHaveValue(`${RAW} Edited.`)
    fail = false
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByRole('heading', { name: 'Holocene' })).toBeInTheDocument()
    expect(calls[2].body).toMatchObject({ input_mode: 'voice', transcript: RAW })
  })

  it('works in Polish', async () => {
    installMicrophone()
    backend()
    const { user } = renderApp()
    await user.click(screen.getByRole('button', { name: 'Polski' }))

    await user.click(await screen.findByRole('button', { name: 'Nagraj' }))
    expect(await screen.findByText('Nagrywanie')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Zatrzymaj i przepisz' }))

    expect(await screen.findByLabelText('Sprawdź transkrypcję')).toHaveValue(RAW)
    expect(screen.getByText(/Wykryty język: polski/)).toBeInTheDocument()
  })
})
