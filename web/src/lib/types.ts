/**
 * the shapes of rows the web app reads, shared by server code and the browser.
 * column names stay snake_case, exactly as MySQL returns them.
 */

/** one row of GET /api/search: a reviewed artist whose name matched. */
export type SearchResult = {
  id: number;
  name: string;
  image_url: string | null;
  review_count: number;
};

/** one floating cover on the home page: a recently reviewed release. */
export type HomeCover = {
  release_id: number;
  title: string;
  cover_url: string;
  artist_id: number;
  artist_name: string;
};

// --- the artist page ---

/** how he related two artists (connections.label). */
export type Label = "sounds_like" | "influenced_by" | "contrast" | "collaborator";

/** the artist the page is about. */
export type Artist = {
  id: number;
  name: string;
  image_url: string | null;
  // MySQL BOOLEAN comes back as 0 or 1
  is_reviewed: number;
};

/**
 * one review in the review box. an album review has a kind, a track review has kind = null.
 * summary and quote are null until the video's captions have been through the ai; until then
 * the box shows fav_tracks (from the description) instead.
 */
export type Review = {
  video_id: string;
  video_title: string;
  title: string;
  kind: "album" | "ep" | "mixtape" | null;
  score_text: string | null;
  summary: string | null;
  quote: string | null;
  quote_start_s: number | null;
  fav_tracks: string[];
};

/**
 * one card in the similar artists grid: another artist linked to this one, plus the newest
 * link with the card's label (for the gray "Fantano linked A → B" line in the track list).
 */
export type SimilarArtist = {
  id: number;
  name: string;
  image_url: string | null;
  video_count: number;
  label: Label;
  link_from_id: number;
  // null for a written "ft." credit: he never said it, it's in a track list
  link_start_s: number | null;
  link_video_id: string;
  link_video_title: string;
};

/** one song he liked (an endorsement), with where he said so. */
export type EndorsedTrack = {
  track_id: number;
  title: string;
  cover_url: string | null;
  artist_id: number;
  source: "fav_track" | "best_track" | "track_review";
  summary: string | null;
  quote: string | null;
  start_s: number | null;
  video_id: string;
  video_title: string;
  // the album whose review listed it as a fav track (null for roundups)
  review_release_title: string | null;
};

/** a row in the track list: the song plus the similar artist it came through. */
export type RecommendedTrack = EndorsedTrack & { artist: SimilarArtist };

/** one spoken mention of an artist he never reviewed. */
export type Mention = {
  other_id: number;
  other_name: string;
  from_artist_id: number;
  label: Label;
  quote: string | null;
  start_s: number;
  video_id: string;
  video_title: string;
};
