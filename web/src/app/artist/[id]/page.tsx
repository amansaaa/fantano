/**
 * the artist page, /artist/{id}.
 *
 * steps:
 *   1. look up the artist (a missing or non-numeric id shows the not-found page)
 *   2. in parallel: their reviews, the similar artists grid, and (for artists he only
 *      mentioned) every spoken mention
 *   3. the songs he liked by the similar artists, then pickRecommendedTracks() picks up to 12
 *
 * left column: photo, name, review box. right column: the grid, then the track list.
 * on phones it's one column in the same order.
 *
 * reads: see src/lib/artist-queries.ts
 */

import type { Metadata } from "next";
import { notFound } from "next/navigation";

import ArtistPhoto from "@/components/ArtistPhoto";
import BackLink from "@/components/BackLink";
import MentionList from "@/components/MentionList";
import ReviewCarousel from "@/components/ReviewCarousel";
import SearchBox from "@/components/SearchBox";
import SectionLabel from "@/components/SectionLabel";
import SimilarArtistsGrid from "@/components/SimilarArtistsGrid";
import TrackList from "@/components/TrackList";
import { getArtist, getEndorsedTracks, getMentions, getReviews, getSimilarArtists } from "@/lib/artist-queries";
import { pickRecommendedTracks } from "@/lib/recommend";
import type { Mention } from "@/lib/types";

// the big photo is 320px wide at most
const PHOTO_PX = 320;
// ids are INT in MySQL, so anything longer can't be one
const ID_PATTERN = /^\d{1,10}$/;

/**
 * the url's id as a number, or null if it isn't one.
 *
 *   parseArtistId("188") -> 188
 *   parseArtistId("abc") -> null
 */
function parseArtistId(rawId: string): number | null {
  return ID_PATTERN.test(rawId) ? Number(rawId) : null;
}

// the browser tab says "Phoebe Bridgers · Fantano"
export async function generateMetadata({ params }: PageProps<"/artist/[id]">): Promise<Metadata> {
  const artistId = parseArtistId((await params).id);
  const artist = artistId === null ? null : await getArtist(artistId);
  return { title: artist ? `${artist.name} · Fantano` : "Artist not found · Fantano" };
}

export default async function ArtistPage({ params }: PageProps<"/artist/[id]">) {
  const artistId = parseArtistId((await params).id);
  const artist = artistId === null ? null : await getArtist(artistId);
  if (!artist) {
    notFound();
  }

  const isReviewed = artist.is_reviewed === 1;
  const noMentions: Mention[] = [];
  const [reviews, similarArtists, mentions] = await Promise.all([
    getReviews(artist.id),
    getSimilarArtists(artist.id),
    isReviewed ? noMentions : getMentions(artist.id),
  ]);

  // contrast cards never contribute songs, so there's no point fetching theirs
  const songArtistIds = similarArtists.filter((similar) => similar.label !== "contrast").map((similar) => similar.id);
  const endorsedTracks = await getEndorsedTracks(songArtistIds);
  const recommendedTracks = pickRecommendedTracks(similarArtists, endorsedTracks);

  return (
    <div className="mx-auto max-w-6xl px-4 pb-24 md:px-8">
      <header className="flex items-center justify-between gap-6 py-6">
        <BackLink />
        <div className="w-full max-w-sm">
          <SearchBox size="small" />
        </div>
      </header>

      <main className="mt-4 grid gap-12 lg:grid-cols-[20rem_1fr] lg:gap-14">
        {/* --- left: who this is and what he thought --- */}
        <aside className="flex flex-col gap-6">
          <ArtistPhoto
            url={artist.image_url}
            name={artist.name}
            sizePx={PHOTO_PX}
            preload
            className="w-full max-w-80 rounded-2xl shadow-[0_18px_40px_-18px_rgba(17,17,20,0.35)]"
          />
          <h1 className="text-3xl font-semibold tracking-tight text-ink">{artist.name}</h1>
          {reviews.length > 0 ? (
            // key: a new artist gets a fresh review box, not the old one's "2 / 6" position
            <ReviewCarousel key={artist.id} reviews={reviews} />
          ) : (
            <p className="text-sm leading-relaxed text-muted">
              Fantano hasn’t reviewed {artist.name} yet. This page is built from the times he brought them up.
            </p>
          )}
        </aside>

        {/* --- right: who he linked them to, and the songs he'd recommend --- */}
        <div className="flex min-w-0 flex-col gap-14">
          <section>
            <SectionLabel>Similar artists according to Fantano</SectionLabel>
            <SimilarArtistsGrid key={artist.id} artists={similarArtists} artistName={artist.name} />
          </section>

          <TrackList tracks={recommendedTracks} pageArtist={artist} />

          {!isReviewed && <MentionList mentions={mentions} artistName={artist.name} />}
        </div>
      </main>
    </div>
  );
}
