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
