/**
 * the "N Tracks Fantano recommends" list. the songs are already picked and ordered by
 * pickRecommendedTracks(); this only draws them. each row shows:
 *   - a gray number, the cover, the title, and the artist (a link to their page)
 *   - the AI summary behind a thin line (never in quotation marks)
 *   - why it's recommended: his real quote + ▶ Watch, or "Fav track in his [Album] review"
 *     when he never talked about it out loud
 *   - why the artist is here, in gray: "Fantano linked A → B · Sounds like ▶ @ 3:12"
 *
 * usage:
 *   <TrackList tracks={recommended} pageArtist={artist} />
 */

import Link from "next/link";

import ArtistPhoto from "@/components/ArtistPhoto";
import SectionLabel from "@/components/SectionLabel";
import WatchLink from "@/components/WatchLink";
import { LABEL_TEXT } from "@/lib/labels";
import type { Artist, RecommendedTrack } from "@/lib/types";
import { formatTime, watchUrl } from "@/lib/youtube";

const COVER_PX = 64;

type Props = {
  tracks: RecommendedTrack[];
  pageArtist: Artist;
};

export default function TrackList({ tracks, pageArtist }: Props) {
  const heading = `${tracks.length} ${tracks.length === 1 ? "Track" : "Tracks"} Fantano recommends`;

  return (
    <section>
      <SectionLabel>{heading}</SectionLabel>

      {tracks.length === 0 && (
        <p className="text-sm text-muted">
          No recommended songs yet. They show up once he’s praised a song by one of the artists above.
        </p>
      )}

      <ol>
        {tracks.map((track, index) => (
          <li key={track.track_id} className="grid grid-cols-[1.75rem_4rem_1fr] gap-x-4 border-t border-line py-6 first:border-t-0 first:pt-0">
            <span className="pt-1 text-xs text-muted tabular-nums">{String(index + 1).padStart(2, "0")}</span>
            <ArtistPhoto url={track.cover_url} name={track.title} sizePx={COVER_PX} kind="cover" className="size-16 rounded-md" />

            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4">
                <h3 className="text-lg font-semibold text-ink">{track.title}</h3>
                <Link href={`/artist/${track.artist.id}`} className="text-sm text-muted hover:text-ink">
                  {track.artist.name}
                </Link>
              </div>

              {track.summary && (
                <p className="mt-2 border-l-2 border-line pl-4 text-[15px] leading-relaxed text-body">{track.summary}</p>
              )}

              <div className="mt-3">
                <WhyRecommended track={track} />
              </div>

              <p className="mt-2 text-xs text-muted">
                <WhyConnected track={track} pageArtist={pageArtist} />
              </p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

// --- the two "why" lines ---

/** his quote + ▶ Watch, or, when he never discussed it aloud, where he listed it. */
function WhyRecommended({ track }: { track: RecommendedTrack }) {
  if (track.quote) {
    return (
      <>
        <p className="text-sm leading-relaxed text-ink">“{track.quote}”</p>
        <WatchLink videoId={track.video_id} startSeconds={track.start_s} videoTitle={track.video_title} />
      </>
    );
  }

  let where = "Liked in his track review";
  if (track.source === "fav_track") {
    where = track.review_release_title ? `Fav track in his ${track.review_release_title} review` : "Fav track in his review";
  }
  if (track.source === "best_track") {
    where = "Best track in his Weekly Track Roundup";
  }
  return (
    <p className="text-sm text-muted">
      {where} <WatchLink videoId={track.video_id} startSeconds={null} />
    </p>
  );
}

/**
 * "Fantano linked Phoebe Bridgers → Lucy Dacus · Collaborator ▶ @ 2:08". the arrow points the
 * way he said it: from the artist being discussed to the one he brought up.
 */
function WhyConnected({ track, pageArtist }: { track: RecommendedTrack; pageArtist: Artist }) {
  const similar = track.artist;
  const saidOnPageArtist = similar.link_from_id === pageArtist.id;
  const fromName = saidOnPageArtist ? pageArtist.name : similar.name;
  const toName = saidOnPageArtist ? similar.name : pageArtist.name;

  return (
    <>
      Fantano linked {fromName} → {toName} · {LABEL_TEXT[similar.label]}
      {similar.link_start_s !== null && (
        <>
          {" "}
          <a
            href={watchUrl(similar.link_video_id, similar.link_start_s)}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-ink hover:underline"
          >
            ▶ @ {formatTime(similar.link_start_s)}
          </a>
        </>
      )}
    </>
  );
}
