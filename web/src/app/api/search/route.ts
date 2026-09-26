/**
 * GET /api/search?q=sza -> the reviewed artists whose name contains what was typed.
 *
 * the search box calls this on every keystroke (after a short pause). only artists he reviewed
 * show up; artists he only mentioned are reachable from other pages but aren't searchable.
 * MySQL's collation ignores case and accents, so "beyonce" finds "Beyoncé" for free.
 *
 * example:
 *   GET /api/search?q=sza
 *   -> [{ "id": 12, "name": "SZA", "image_url": "https://cdn-images.dzcdn.net/...", "review_count": 2 }]
 *
 * reads: artists, reviews
 */

import { query } from "@/lib/db";
import type { SearchResult } from "@/lib/types";

const MAX_RESULTS = 8;
// nobody types a 100 character artist name, so anything longer is cut off
const MAX_QUERY_LENGTH = 100;

// names that start with what was typed come first ("sza" -> "SZA" before "Ashe & SZA"),
// then alphabetical
const SEARCH_SQL = `
SELECT artists.id, artists.name, artists.image_url,
       (SELECT COUNT(*) FROM reviews WHERE reviews.artist_id = artists.id) AS review_count
FROM artists
WHERE artists.is_reviewed AND artists.name LIKE CONCAT('%', ?, '%')
ORDER BY artists.name LIKE CONCAT(?, '%') DESC, artists.name
LIMIT ${MAX_RESULTS}
`;

/**
 * LIKE treats % and _ as wildcards, so typing "%" would match every artist. a backslash in
 * front makes them plain characters again:
 *
 *   escapeLike("100%") -> "100\\%"
 *   escapeLike("sza")  -> "sza"
 */
function escapeLike(text: string): string {
  return text.replace(/[\\%_]/g, (character) => `\\${character}`);
}

export async function GET(request: Request) {
  const typed = new URL(request.url).searchParams.get("q") ?? "";
  const searchText = typed.trim().slice(0, MAX_QUERY_LENGTH);
  if (!searchText) {
    return Response.json([]);
  }

  const escaped = escapeLike(searchText);
  const results = await query<SearchResult>(SEARCH_SQL, [escaped, escaped]);
  return Response.json(results);
}
