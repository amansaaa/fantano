/**
 * the home page: the logo, the headline, the search box, and covers of his newest reviews
 * floating around them.
 *
 * reads: reviews, releases, artists, videos (the covers)
 */

import Image from "next/image";

import FloatingCovers, { COVER_COUNT } from "@/components/FloatingCovers";
import SearchBox from "@/components/SearchBox";
import { query } from "@/lib/db";
import type { HomeCover } from "@/lib/types";

// album reviews only (track reviews have no release), newest video first
const NEWEST_COVERS_SQL = `
SELECT releases.id AS release_id, releases.title, releases.cover_url,
       artists.id AS artist_id, artists.name AS artist_name
FROM reviews
JOIN releases ON releases.id = reviews.release_id
JOIN artists ON artists.id = reviews.artist_id
JOIN videos ON videos.id = reviews.video_id
WHERE releases.cover_url IS NOT NULL
ORDER BY videos.published_at DESC
LIMIT ${COVER_COUNT}
`;

const LOGO_PX = 88;

export default async function HomePage() {
  const covers = await query<HomeCover>(NEWEST_COVERS_SQL);

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden px-4">
      <FloatingCovers covers={covers} />

      <div className="relative z-10 flex w-full max-w-3xl flex-col items-center text-center">
        <Image src="/logo.png" alt="Anthony Fantano" width={LOGO_PX} height={LOGO_PX} preload />
        <h1 className="mt-6 text-4xl leading-[1.15] font-medium tracking-tight text-ink md:text-5xl">
          Discover music from the <br className="hidden md:inline" />
          internet’s busiest music nerd
        </h1>
        <div className="mt-10 w-full max-w-xl">
          <SearchBox size="large" autoFocus />
        </div>
      </div>
    </main>
  );
}
