/**
 * every query the artist page runs, in plain sql. the page calls these in parallel.
 *
 * usage (server only):
 *   const artist = await getArtist(188);                  // { id: 188, name: "Phoebe Bridgers", ... } or null
 *   const similar = await getSimilarArtists(188);         // the grid, already ranked
 *   const tracks = await getEndorsedTracks([28, 193]);    // songs he liked by those artists
 *
 * reads: artists, reviews, releases, tracks, videos, connections, endorsements
 */

import { cache } from "react";

import { query } from "@/lib/db";
import type { Artist, EndorsedTrack, Mention, Review, SimilarArtist } from "@/lib/types";

// --- the artist ---

const ARTIST_SQL = "SELECT id, name, image_url, is_reviewed FROM artists WHERE id = ?";

/**
 * the artist, or null if the id doesn't exist. wrapped in react's cache() because the page
 * and its <title> (generateMetadata) both ask for it, and this makes that one query.
 */
export const getArtist = cache(async (artistId: number): Promise<Artist | null> => {
  const rows = await query<Artist>(ARTIST_SQL, [artistId]);
  return rows[0] ?? null;
});

// --- the review box ---

// an album review has a release, a track review has a track, never both (a CHECK in schema.sql)
const REVIEWS_SQL = `
SELECT reviews.video_id, videos.title AS video_title,
       COALESCE(releases.title, tracks.title) AS title, releases.kind,
       reviews.score_text, reviews.summary, reviews.quote, reviews.quote_start_s
FROM reviews
JOIN videos ON videos.id = reviews.video_id
LEFT JOIN releases ON releases.id = reviews.release_id
LEFT JOIN tracks ON tracks.id = reviews.track_id
WHERE reviews.artist_id = ?
ORDER BY videos.published_at DESC
`;

// the fav tracks listed in each review's description, in the order he wrote them
// (load.py inserts them in that order, so endorsements.id keeps it)
const FAV_TRACKS_SQL = `
SELECT endorsements.video_id, tracks.title
FROM endorsements
JOIN tracks ON tracks.id = endorsements.track_id
WHERE endorsements.video_id IN (?) AND endorsements.source = 'fav_track'
ORDER BY endorsements.id
`;

/**
 * this artist's reviews, newest first, each with its fav tracks. empty for artists he only
 * mentioned.
 *
 *   await getReviews(239)
 *   // -> [{ title: "petal", score_text: "5/10", summary: "He finds...", fav_tracks: ["...", ...], ... }]
 */
export async function getReviews(artistId: number): Promise<Review[]> {
  const reviews = await query<Omit<Review, "fav_tracks">>(REVIEWS_SQL, [artistId]);
  if (reviews.length === 0) {
    return [];
  }

  const favRows = await query<{ video_id: string; title: string }>(
    FAV_TRACKS_SQL,
    [reviews.map((review) => review.video_id)],
  );
  const favTracksByVideo = new Map<string, string[]>();
  for (const row of favRows) {
    const favTracks = favTracksByVideo.get(row.video_id) ?? [];
    favTracks.push(row.title);
    favTracksByVideo.set(row.video_id, favTracks);
  }

  return reviews.map((review) => ({ ...review, fav_tracks: favTracksByVideo.get(review.video_id) ?? [] }));
}

// --- the similar artists grid ---

// the whole grid rule in one query (CLAUDE.md §6):
//   links        every connection where this artist is the "from" OR the "to" side,
//                with other_id = whoever is on the other side. it's two halves glued with
//                UNION ALL instead of "WHERE ? IN (from_artist_id, to_artist_id)", because
//                MySQL can't use an index for that IN and scans the whole table; each half
//                uses its own index (from_artist_id, to_artist_id). a connection is never
//                from and to the same artist (a CHECK in schema.sql), so nothing is counted twice
//   pairs        per other artist: how many different videos link them, and the newest one
//   label_ranks  per other artist: their labels, most frequent first. ties go to the newer
//                video, then to whatever he said first
//   latest_links per other artist and label: the newest link, for the gray
//                "Fantano linked A → B · Sounds like ▶ @ 3:12" line (or, for a written
//                "ft." credit with no timestamp, "A ft. B · Collaborator · credited in {video}")
// ranked by number of videos, then the newest video
const SIMILAR_ARTISTS_SQL = `
WITH links AS (
  SELECT connections.to_artist_id AS other_id,
         connections.from_artist_id, connections.label, connections.start_s,
         connections.video_id, videos.title AS video_title, videos.published_at
  FROM connections
  JOIN videos ON videos.id = connections.video_id
  WHERE connections.from_artist_id = ?
  UNION ALL
  SELECT connections.from_artist_id AS other_id,
         connections.from_artist_id, connections.label, connections.start_s,
         connections.video_id, videos.title AS video_title, videos.published_at
  FROM connections
  JOIN videos ON videos.id = connections.video_id
  WHERE connections.to_artist_id = ?
),
pairs AS (
  SELECT other_id, COUNT(DISTINCT video_id) AS video_count, MAX(published_at) AS newest_at
  FROM links
  GROUP BY other_id
),
label_ranks AS (
  SELECT other_id, label,
         ROW_NUMBER() OVER (
           PARTITION BY other_id
           ORDER BY COUNT(*) DESC, MAX(published_at) DESC, MIN(start_s) IS NULL, MIN(start_s)
         ) AS label_rank
  FROM links
  GROUP BY other_id, label
),
latest_links AS (
  SELECT other_id, label, from_artist_id, start_s, video_id, video_title,
         ROW_NUMBER() OVER (
           PARTITION BY other_id, label
           ORDER BY published_at DESC, start_s IS NULL, start_s
         ) AS link_rank
  FROM links
)
SELECT artists.id, artists.name, artists.image_url, pairs.video_count, label_ranks.label,
       latest_links.from_artist_id AS link_from_id, latest_links.start_s AS link_start_s,
       latest_links.video_id AS link_video_id, latest_links.video_title AS link_video_title
FROM pairs
JOIN artists ON artists.id = pairs.other_id
JOIN label_ranks ON label_ranks.other_id = pairs.other_id AND label_ranks.label_rank = 1
JOIN latest_links ON latest_links.other_id = pairs.other_id
                 AND latest_links.label = label_ranks.label
                 AND latest_links.link_rank = 1
ORDER BY pairs.video_count DESC, pairs.newest_at DESC, artists.name
`;

/** every artist linked to this one, ranked for the grid. */
export async function getSimilarArtists(artistId: number): Promise<SimilarArtist[]> {
  return query<SimilarArtist>(SIMILAR_ARTISTS_SQL, [artistId, artistId]);
}

// --- the recommended tracks ---

// newest first, which pickRecommendedTracks relies on. reviews/releases are LEFT JOINed only to
// name the album for "Fav track in his [Album] review" (roundups have no review row)
const ENDORSED_TRACKS_SQL = `
SELECT tracks.id AS track_id, tracks.title, tracks.cover_url, tracks.artist_id,
       endorsements.source, endorsements.summary, endorsements.quote, endorsements.start_s,
       endorsements.video_id, videos.title AS video_title,
       releases.title AS review_release_title
FROM endorsements
JOIN tracks ON tracks.id = endorsements.track_id
JOIN videos ON videos.id = endorsements.video_id
LEFT JOIN reviews ON reviews.video_id = endorsements.video_id
LEFT JOIN releases ON releases.id = reviews.release_id
WHERE tracks.artist_id IN (?)
ORDER BY videos.published_at DESC, endorsements.start_s IS NULL, endorsements.start_s
`;

/**
 * every song he liked by these artists, newest first. mysql2 turns the array into a list:
 * [28, 193] -> IN (28, 193).
 */
export async function getEndorsedTracks(artistIds: number[]): Promise<EndorsedTrack[]> {
  // "IN ()" is a sql error, and there's nothing to look up anyway
  if (artistIds.length === 0) {
    return [];
  }
  return query<EndorsedTrack>(ENDORSED_TRACKS_SQL, [artistIds]);
}

// --- artists he only mentioned ---

// only spoken links (they have a timestamp). written ft. credits have nothing to play.
// same two-halves UNION ALL as the grid, so both halves use an index
const MENTIONS_SQL = `
SELECT other_id, other_name, from_artist_id, label, quote, start_s, video_id, video_title
FROM (
  SELECT other_artists.id AS other_id, other_artists.name AS other_name,
         connections.from_artist_id, connections.label, connections.quote, connections.start_s,
         connections.video_id, videos.title AS video_title, videos.published_at
  FROM connections
  JOIN videos ON videos.id = connections.video_id
  JOIN artists AS other_artists ON other_artists.id = connections.to_artist_id
  WHERE connections.from_artist_id = ? AND connections.start_s IS NOT NULL
  UNION ALL
  SELECT other_artists.id AS other_id, other_artists.name AS other_name,
         connections.from_artist_id, connections.label, connections.quote, connections.start_s,
         connections.video_id, videos.title AS video_title, videos.published_at
  FROM connections
  JOIN videos ON videos.id = connections.video_id
  JOIN artists AS other_artists ON other_artists.id = connections.from_artist_id
  WHERE connections.to_artist_id = ? AND connections.start_s IS NOT NULL
) AS mentions
ORDER BY published_at DESC, start_s
`;

/** "Every time Fantano mentioned X": each spoken link to this artist, newest first. */
export async function getMentions(artistId: number): Promise<Mention[]> {
  return query<Mention>(MENTIONS_SQL, [artistId, artistId]);
}
