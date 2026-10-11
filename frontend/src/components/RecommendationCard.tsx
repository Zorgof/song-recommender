import { useTranslation } from 'react-i18next'

/** The song fields shared by a fresh recommendation and a history item. */
export interface SongView {
  title: string
  artist: string
  album_art_url: string | null
  spotify_url: string | null
  spotify_track_id: string | null
  spotify_verified: boolean
  youtube_url: string | null
  youtube_verified: boolean
  explanation: string | null
  need_summary: string | null
  trace_url: string | null
}

interface Props {
  song: SongView
  // History view: smaller, no embedded player.
  compact?: boolean
}

function spotifyEmbedUrl(trackId: string): string {
  return `https://open.spotify.com/embed/track/${encodeURIComponent(trackId)}`
}

export function RecommendationCard({ song, compact = false }: Props) {
  const { t } = useTranslation()
  const Heading = compact ? 'h3' : 'h2'
  const SubHeading = compact ? 'h4' : 'h3'
  // FR-18: the player only for a verified track.
  const embedTrackId = song.spotify_verified ? song.spotify_track_id : null

  return (
    <article className="space-y-4 rounded-lg bg-white p-6 shadow-sm dark:bg-slate-800">
      <div className="flex items-center gap-4">
        {song.album_art_url && (
          <img
            src={song.album_art_url}
            alt={t('result.albumArt', { title: song.title })}
            className={`${compact ? 'size-16' : 'size-24'} shrink-0 rounded-md object-cover shadow`}
          />
        )}
        <div className="min-w-0">
          {!compact && (
            <p className="text-sm font-semibold tracking-wide text-emerald-700 uppercase dark:text-emerald-400">
              {t('result.heading')}
            </p>
          )}
          <Heading className={`${compact ? 'text-lg' : 'text-2xl'} font-bold break-words`}>
            {song.title}
          </Heading>
          <p className="text-slate-600 dark:text-slate-300">{song.artist}</p>
        </div>
      </div>

      {!compact && embedTrackId && (
        <iframe
          src={spotifyEmbedUrl(embedTrackId)}
          title={t('result.player', { title: song.title, artist: song.artist })}
          width="100%"
          height="152"
          loading="lazy"
          allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
          className="rounded-xl border-0"
        />
      )}

      <div className="flex flex-wrap gap-3">
        {song.spotify_url && (
          <SongLink
            href={song.spotify_url}
            verified={song.spotify_verified}
            label={song.spotify_verified ? t('result.spotify') : t('result.spotifySearch')}
          />
        )}
        {song.youtube_url && (
          <SongLink
            href={song.youtube_url}
            verified={song.youtube_verified}
            label={song.youtube_verified ? t('result.youtube') : t('result.youtubeSearch')}
          />
        )}
      </div>

      {song.need_summary && (
        <section>
          <SubHeading className="text-sm font-semibold text-slate-500 dark:text-slate-400">
            {t('result.need')}
          </SubHeading>
          <p>{song.need_summary}</p>
        </section>
      )}
      {song.explanation && (
        <section>
          <SubHeading className="text-sm font-semibold text-slate-500 dark:text-slate-400">
            {t('result.why')}
          </SubHeading>
          <p>{song.explanation}</p>
        </section>
      )}

      {song.trace_url && (
        <a
          href={song.trace_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block text-sm text-slate-500 underline hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100"
        >
          {t('result.trace')}
        </a>
      )}
    </article>
  )
}

function SongLink({ href, label, verified }: { href: string; label: string; verified: boolean }) {
  const { t } = useTranslation()
  return (
    <span className="inline-flex items-center gap-2">
      <a href={href} target="_blank" rel="noopener noreferrer" className="btn-secondary">
        {label}
      </a>
      {/* FR-17: a fallback search link is clearly marked. */}
      {!verified && (
        <span
          title={t('result.unverifiedHint')}
          className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-900 dark:text-amber-100"
        >
          {t('result.unverified')}
        </span>
      )}
    </span>
  )
}
