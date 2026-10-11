import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { setLocale } from '../i18n'
import { recommendation, renderWithProviders } from '../test/utils'
import { RecommendationCard } from './RecommendationCard'

describe('RecommendationCard', () => {
  it('shows a verified song with the Spotify player and links', () => {
    renderWithProviders(<RecommendationCard song={recommendation()} />)

    expect(screen.getByRole('heading', { level: 2, name: 'Holocene' })).toBeInTheDocument()
    expect(screen.getByText('Bon Iver')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Album art of Holocene' })).toHaveAttribute(
      'src',
      'https://i.scdn.co/image/holocene',
    )
    expect(screen.getByTitle('Spotify player: Holocene by Bon Iver')).toHaveAttribute(
      'src',
      'https://open.spotify.com/embed/track/4fbvXwMTXPWaFyaMWUm9CR',
    )
    const spotify = screen.getByRole('link', { name: 'Open in Spotify' })
    expect(spotify).toHaveAttribute('href', 'https://open.spotify.com/track/4fbvXwMTXPWaFyaMWUm9CR')
    expect(spotify).toHaveAttribute('target', '_blank')
    expect(spotify).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByRole('link', { name: 'Watch on YouTube' })).toBeInTheDocument()
    expect(screen.getByText('You are tired and want to relax.')).toBeInTheDocument()
    expect(screen.getByText('A slow, warm song to help you unwind.')).toBeInTheDocument()
    expect(screen.queryByText('unverified')).not.toBeInTheDocument()
  })

  it('marks fallback search links as unverified and shows no player', () => {
    const song = recommendation({
      spotify_verified: false,
      spotify_track_id: null,
      spotify_url: 'https://open.spotify.com/search/Holocene%20Bon%20Iver',
      youtube_verified: false,
      youtube_url: 'https://www.youtube.com/results?search_query=Holocene+Bon+Iver',
    })
    renderWithProviders(<RecommendationCard song={song} />)

    expect(screen.getByRole('link', { name: 'Search on Spotify' })).toHaveAttribute(
      'href',
      song.spotify_url,
    )
    expect(screen.getByRole('link', { name: 'Search on YouTube' })).toBeInTheDocument()
    const badges = screen.getAllByText('unverified')
    expect(badges).toHaveLength(2)
    expect(badges[0]).toHaveAttribute(
      'title',
      'We could not confirm this link; it opens a search instead.',
    )
    expect(screen.queryByTitle(/Spotify player/)).not.toBeInTheDocument()
  })

  it('marks only the link that is unverified', () => {
    renderWithProviders(<RecommendationCard song={recommendation({ youtube_verified: false })} />)

    expect(screen.getAllByText('unverified')).toHaveLength(1)
    expect(screen.getByRole('link', { name: 'Search on YouTube' })).toBeInTheDocument()
    expect(screen.getByTitle(/Spotify player/)).toBeInTheDocument()
  })

  it('links to the trace only when tracing is on', () => {
    const traceUrl = 'https://smith.langchain.com/o/x/projects/p/y/r/req-1?poll=true'
    const { rerender } = renderWithProviders(<RecommendationCard song={recommendation()} />)
    expect(screen.queryByRole('link', { name: 'View trace in LangSmith' })).not.toBeInTheDocument()

    rerender(<RecommendationCard song={recommendation({ trace_url: traceUrl })} />)
    expect(screen.getByRole('link', { name: 'View trace in LangSmith' })).toHaveAttribute(
      'href',
      traceUrl,
    )
  })

  it('is compact in the history: smaller heading, no player', () => {
    renderWithProviders(<RecommendationCard song={recommendation()} compact />)

    expect(screen.getByRole('heading', { level: 3, name: 'Holocene' })).toBeInTheDocument()
    expect(screen.queryByTitle(/Spotify player/)).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open in Spotify' })).toBeInTheDocument()
  })

  it('translates its labels', async () => {
    await setLocale('pl')
    renderWithProviders(<RecommendationCard song={recommendation({ youtube_verified: false })} />)

    expect(screen.getByRole('link', { name: 'Otwórz w Spotify' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Szukaj na YouTube' })).toBeInTheDocument()
    expect(screen.getByText('niezweryfikowany')).toBeInTheDocument()
    expect(screen.getByText('Dlaczego ta piosenka')).toBeInTheDocument()
  })
})
