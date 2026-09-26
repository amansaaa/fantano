/**
 * the "N songs Fantano liked by these artists" list: songs by the connected artists that are
 * on one of his lists. the songs are already picked and ordered by pickRecommendedTracks();
 * this only draws them. each row shows:
 *   - a gray number, the cover, the title, and the artist (a link to their page)
 *   - which list it's on: "Fav track in his Mudboy review ▶ Watch ↗"
 *   - why that artist is on this page, in gray:
 *     "Why Sheck Wes: has a song with Travis Scott, credited in {roundup} ↗"
 *
 * those two lines come from two different videos: the song line is about the connected
 * artist's own review, the gray line is the credit that connects them to this page's artist.
 *
 * usage:
 *   <TrackList tracks={recommended} pageArtist={artist} />
 */

import Link from "next/link";

import ArtistPhoto from "@/components/ArtistPhoto";
import SectionLabel from "@/components/SectionLabel";
import WatchLink from "@/components/WatchLink";
import type { Artist, RecommendedTrack } from "@/lib/types";
import { watchUrl } from "@/lib/youtube";

const COVER_PX = 64;

type Props = {
  tracks: RecommendedTrack[];
  pageArtist: Artist;
};

export default function TrackList({ tracks, pageArtist }: Props) {
  const heading = `${tracks.length} ${tracks.length === 1 ? "song" : "songs"} Fantano liked by these artists`;

  return (
    <section>
      <SectionLabel>{heading}</SectionLabel>

      {tracks.length === 0 && (
        <p className="text-sm text-muted">None of these artists have a song on his fav or best lists yet.</p>
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

              <div className="mt-3">
                <WhichList track={track} />
              </div>

              <p className="mt-2 truncate text-xs text-muted">
                <WhyConnected track={track} pageArtist={pageArtist} />
              </p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

// --- the two lines under each song ---

/**
 * which of his lists the song is on, and the video it's from:
 *   fav_track    "Fav track in his Mudboy review ▶ Watch ↗"
 *   best_track   "Best track in his Weekly Track Roundup ▶ Watch ↗"
 */
function WhichList({ track }: { track: RecommendedTrack }) {
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
 * why this song's artist is on the page at all: the newest video that credits them together.
 *   "Why Sheck Wes: has a song with Travis Scott, credited in “Sheck Wes, Lana Del Rey… | Weekly Track Roundup” ↗"
 */
function WhyConnected({ track, pageArtist }: { track: RecommendedTrack; pageArtist: Artist }) {
  const connected = track.artist;
  return (
    <>
      Why {connected.name}: has a song with {pageArtist.name},{" "}
      <a
        href={watchUrl(connected.link_video_id, null)}
        target="_blank"
        rel="noopener noreferrer"
        className="hover:text-ink hover:underline"
      >
        credited in “{connected.link_video_title}” ↗
      </a>
    </>
  );
}
