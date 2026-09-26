/**
 * tests for src/lib/recommend.ts: the round-robin rule behind "N Tracks Fantano recommends".
 * each test is one part of the rule: grid order, skipping contrast, the cap, grouping, and
 * one row per song.
 */

import { describe, expect, test } from "vitest";

import { pickRecommendedTracks } from "../src/lib/recommend";
import type { EndorsedTrack, Label, SimilarArtist } from "../src/lib/types";

/** one grid card. only id and label matter to the rule. */
function makeArtist(id: number, label: Label = "sounds_like"): SimilarArtist {
  return {
    id, name: `artist ${id}`, image_url: null, video_count: 1, label,
    link_from_id: 1, link_start_s: 10, link_video_id: "abc123XYZ00", link_video_title: "a video",
  };
}

/** one endorsed song by an artist. */
function makeTrack(trackId: number, artistId: number, videoId = "abc123XYZ00"): EndorsedTrack {
  return {
    track_id: trackId, title: `song ${trackId}`, cover_url: null, artist_id: artistId,
    source: "best_track", summary: null, quote: null, start_s: null,
    video_id: videoId, video_title: "a video", review_release_title: null,
  };
}

/** just the song ids, in the order they'd be shown. */
function pickedIds(artists: SimilarArtist[], tracks: EndorsedTrack[], limit?: number): number[] {
  return pickRecommendedTracks(artists, tracks, limit).map((track) => track.track_id);
}

describe("pickRecommendedTracks", () => {
  test("takes one song per artist per round, then groups each artist's songs", () => {
    const artists = [makeArtist(1), makeArtist(2)];
    // artist 1 has songs 10, 11, 12. artist 2 has song 20
    const tracks = [makeTrack(10, 1), makeTrack(11, 1), makeTrack(12, 1), makeTrack(20, 2)];
    // picked in the order 10, 20, 11 (limit 3), then shown grouped: 10, 11, 20
    expect(pickedIds(artists, tracks, 3)).toEqual([10, 11, 20]);
  });

  test("the round-robin spreads the limit across artists instead of filling up on the first", () => {
    const artists = [makeArtist(1), makeArtist(2), makeArtist(3)];
    const tracks = [
      makeTrack(10, 1), makeTrack(11, 1), makeTrack(12, 1), makeTrack(13, 1),
      makeTrack(20, 2), makeTrack(21, 2),
      makeTrack(30, 3),
    ];
    // rounds: [10, 20, 30] then [11, 21] -> 5 songs, capped at 4 -> 10, 20, 30, 11
    expect(pickedIds(artists, tracks, 4)).toEqual([10, 11, 20, 30]);
  });

  test("skips artists labeled contrast", () => {
    const artists = [makeArtist(1, "contrast"), makeArtist(2)];
    const tracks = [makeTrack(10, 1), makeTrack(20, 2)];
    expect(pickedIds(artists, tracks)).toEqual([20]);
  });

  test("stops at 12 by default", () => {
    const artists = [makeArtist(1)];
    const tracks = Array.from({ length: 20 }, (_, index) => makeTrack(100 + index, 1));
    expect(pickedIds(artists, tracks)).toHaveLength(12);
  });

  test("follows grid order, not the order the songs came in", () => {
    const artists = [makeArtist(2), makeArtist(1)];
    const tracks = [makeTrack(10, 1), makeTrack(20, 2)];
    expect(pickedIds(artists, tracks)).toEqual([20, 10]);
  });

  test("a song endorsed in two videos shows once, from the newest video", () => {
    const artists = [makeArtist(1)];
    // tracks arrive newest first, so the first copy is the newest
    const tracks = [makeTrack(10, 1, "newVideo000"), makeTrack(10, 1, "oldVideo000")];
    const picked = pickRecommendedTracks(artists, tracks);
    expect(picked).toHaveLength(1);
    expect(picked[0].video_id).toBe("newVideo000");
  });

  test("no songs by any similar artist -> an empty list", () => {
    expect(pickedIds([makeArtist(1)], [])).toEqual([]);
  });
});
