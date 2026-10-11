import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { apiError, mockFetch, renderWithProviders } from '../test/utils'
import { FeedbackButtons } from './FeedbackButtons'

const noContent = () => new Response(null, { status: 204 })

describe('FeedbackButtons', () => {
  it('sends a thumb at once, then the comment with it', async () => {
    const calls = mockFetch(noContent)
    const { user } = renderWithProviders(<FeedbackButtons requestId="req-1" />)
    expect(screen.queryByLabelText('Comment (optional)')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /It fits/ }))

    expect(await screen.findByText('Thanks! Your rating is saved.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /It fits/ })).toHaveAttribute('aria-pressed', 'true')
    await user.type(screen.getByLabelText('Comment (optional)'), '  Perfect for tonight.  ')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(calls).toEqual([
      { method: 'POST', path: '/recommendations/req-1/feedback', body: { score: 'up' } },
      {
        method: 'POST',
        path: '/recommendations/req-1/feedback',
        body: { score: 'up', comment: 'Perfect for tonight.' },
      },
    ])
  })

  it('changes the rating', async () => {
    const calls = mockFetch(noContent)
    const { user } = renderWithProviders(
      <FeedbackButtons
        requestId="req-1"
        initial={{ score: 'up', comment: 'Nice', synced_to_langsmith: true }}
      />,
    )
    expect(screen.getByRole('button', { name: /It fits/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByLabelText('Comment (optional)')).toHaveValue('Nice')

    await user.click(screen.getByRole('button', { name: /It doesn't fit/ }))

    expect(await screen.findByText('Thanks! Your rating is saved.')).toBeInTheDocument()
    expect(calls[0].body).toEqual({ score: 'down', comment: 'Nice' })
    expect(screen.getByRole('button', { name: /It doesn't fit/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('tells when a stored rating has not reached LangSmith', () => {
    renderWithProviders(
      <FeedbackButtons
        requestId="req-1"
        initial={{ score: 'down', comment: null, synced_to_langsmith: false }}
      />,
    )

    expect(screen.getByText(/Saved locally/)).toBeInTheDocument()
  })

  it('shows an error when saving fails', async () => {
    mockFetch(() => apiError('not_found', 404))
    const { user } = renderWithProviders(<FeedbackButtons requestId="gone" />)

    await user.click(screen.getByRole('button', { name: /It fits/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This recommendation no longer exists.',
    )
  })
})
