/**
 * the album covers scattered around the home page search box. each one links to its artist.
 *
 * the covers come from the database (the newest reviews), and the spots are fixed below,
 * so cover #1 always lands in spot #1. on phones only the first 4 spots show, so covers never
 * sit on top of the search box.
 *
 * usage:
 *   <FloatingCovers covers={covers} />   // covers from the home page query, newest first
 */

import Image from "next/image";
import Link from "next/link";
import type { CSSProperties } from "react";

import type { HomeCover } from "@/lib/types";

type Spot = {
  // where it sits, as css offsets from the page edges ("9%" or "4%")
  position: CSSProperties;
  sizePx: number;
  // phones only have room for the spots above and below the headline
  showOnPhone: boolean;
};

// laid out like data/ui-reference/home.jpg: a loose ring around the middle
const SPOTS: Spot[] = [
  { position: { top: "9%", left: "7%" }, sizePx: 112, showOnPhone: true },
  { position: { top: "7%", right: "8%" }, sizePx: 100, showOnPhone: true },
  { position: { bottom: "8%", left: "8%" }, sizePx: 112, showOnPhone: true },
  { position: { bottom: "10%", right: "7%" }, sizePx: 128, showOnPhone: true },
  { position: { top: "13%", left: "29%" }, sizePx: 144, showOnPhone: false },
  { position: { top: "11%", right: "22%" }, sizePx: 120, showOnPhone: false },
  { position: { top: "45%", left: "3%" }, sizePx: 116, showOnPhone: false },
  { position: { top: "43%", right: "5%" }, sizePx: 84, showOnPhone: false },
  { position: { bottom: "12%", left: "30%" }, sizePx: 100, showOnPhone: false },
  { position: { bottom: "7%", right: "33%" }, sizePx: 104, showOnPhone: false },
];

export const COVER_COUNT = SPOTS.length;

// every cover bobs on its own schedule instead of all moving together
const FLOAT_DELAY_STEP_SECONDS = 0.9;

export default function FloatingCovers({ covers }: { covers: HomeCover[] }) {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0">
      {covers.slice(0, SPOTS.length).map((cover, index) => {
        const spot = SPOTS[index];
        return (
          <Link
            key={cover.release_id}
            href={`/artist/${cover.artist_id}`}
            tabIndex={-1}
            title={`${cover.artist_name} – ${cover.title}`}
            style={{ ...spot.position, animationDelay: `-${index * FLOAT_DELAY_STEP_SECONDS}s` }}
            className={`pointer-events-auto absolute animate-float motion-reduce:animate-none ${
              spot.showOnPhone ? "" : "hidden md:block"
            }`}
          >
            <Image
              src={cover.cover_url}
              alt={`${cover.artist_name} – ${cover.title}`}
              width={spot.sizePx}
              height={spot.sizePx}
              // the phone size is 70% of the desktop one
              className="w-[calc(var(--size)*0.7)] bg-placeholder shadow-[0_14px_30px_-10px_rgba(17,17,20,0.35)] transition-transform duration-300 hover:scale-105 md:w-(--size)"
              style={{ "--size": `${spot.sizePx}px` } as CSSProperties}
            />
          </Link>
        );
      })}
    </div>
  );
}
