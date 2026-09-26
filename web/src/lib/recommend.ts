/**
 * the "N Tracks Fantano recommends" rule (CLAUDE.md §6), as one pure function:
 *
 *   pick songs round-robin across the similar artists (in grid order, skipping cards labeled
 *   Contrast) until there are 12, then show each artist's songs together.
 *
 * no database here, so it's tested in tests/recommend.test.ts.
 *
 * example, grid = [Frank Ocean, Doja Cat (contrast), Kendrick], limit 3:
 *   Frank Ocean: [Nights, Ivy]   Doja Cat: [Paint the Town Red]   Kendrick: [Alright]
 *   round 1 -> Nights, Alright   round 2 -> Ivy   (Doja Cat is skipped: contrast)
 *   grouped -> [Nights, Ivy, Alright]
 */

import type { EndorsedTrack, RecommendedTrack, SimilarArtist } from "@/lib/types";

export const MAX_RECOMMENDED_TRACKS = 12;

/**
 * picks the recommended songs. `tracks` must be newest first (the sql sorts them), so when a
 * song was endorsed in two videos, the newest endorsement is the one kept.
 */
export function pickRecommendedTracks(
  similarArtists: SimilarArtist[],
  tracks: EndorsedTrack[],
  limit: number = MAX_RECOMMENDED_TRACKS,
): RecommendedTrack[] {
  // --- each artist's songs, newest first, one row per song ---
  const songsByArtist = new Map<number, EndorsedTrack[]>();
  const seenTrackIds = new Set<number>();
  for (const track of tracks) {
    if (seenTrackIds.has(track.track_id)) {
      continue;
    }
    seenTrackIds.add(track.track_id);
    const songs = songsByArtist.get(track.artist_id) ?? [];
    songs.push(track);
    songsByArtist.set(track.artist_id, songs);
  }

  // --- the artists that can contribute, in grid order ---
  const eligibleArtists: SimilarArtist[] = [];
  for (const artist of similarArtists) {
    if (artist.label === "contrast") {
      continue;
    }
    if (!songsByArtist.has(artist.id)) {
      continue;
    }
    eligibleArtists.push(artist);
  }

  // --- round-robin: one song from each artist per round, until the limit or nothing's left ---
  const pickedByArtist = new Map<number, RecommendedTrack[]>();
  let pickedCount = 0;
  let round = 0;
  let pickedThisRound = true;
  while (pickedCount < limit && pickedThisRound) {
    pickedThisRound = false;
    for (const artist of eligibleArtists) {
      if (pickedCount >= limit) {
        break;
      }
      const song = songsByArtist.get(artist.id)![round];
      if (!song) {
        continue;
      }
      const picked = pickedByArtist.get(artist.id) ?? [];
      picked.push({ ...song, artist });
      pickedByArtist.set(artist.id, picked);
      pickedCount += 1;
      pickedThisRound = true;
    }
    round += 1;
  }

  // --- each artist's songs together, artists still in grid order ---
  const grouped: RecommendedTrack[] = [];
  for (const artist of eligibleArtists) {
    grouped.push(...(pickedByArtist.get(artist.id) ?? []));
  }
  return grouped;
}
