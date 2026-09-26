"use client";

/**
 * the "Artists connected to X" grid: a photo, name, and label for each artist who shares a
 * song credit with this one ("Sheck Wes - ILMB ft. Travis Scott" in a roundup), already ranked
 * by the sql (most videos first). the top 12 show, and "Show all N" reveals the rest. each card
 * opens that artist's page.
 *
 * usage:
 *   <SimilarArtistsGrid artists={similarArtists} />
 */

import Link from "next/link";
import { useState } from "react";

import ArtistPhoto from "@/components/ArtistPhoto";
import { LABEL_TEXT } from "@/lib/labels";
import type { SimilarArtist } from "@/lib/types";

const CARDS_SHOWN_AT_FIRST = 12;
// the biggest a grid photo gets (6 across on a wide screen)
const CARD_PHOTO_PX = 140;

export default function SimilarArtistsGrid({ artists }: { artists: SimilarArtist[] }) {
  const [showAll, setShowAll] = useState(false);

  if (artists.length === 0) {
    return <p className="text-sm text-muted">No connected artists yet.</p>;
  }

  const shown = showAll ? artists : artists.slice(0, CARDS_SHOWN_AT_FIRST);
  const hiddenCount = artists.length - CARDS_SHOWN_AT_FIRST;

  return (
    <div>
      <ul className="grid grid-cols-3 gap-x-4 gap-y-6 sm:grid-cols-4 lg:grid-cols-6">
        {shown.map((artist) => (
          <li key={artist.id}>
            <Link href={`/artist/${artist.id}`} className="group block">
              <ArtistPhoto
                url={artist.image_url}
                name={artist.name}
                sizePx={CARD_PHOTO_PX}
                className="w-full rounded-md transition-opacity group-hover:opacity-85"
              />
              <p className="mt-2 line-clamp-2 text-sm leading-snug font-semibold text-ink">{artist.name}</p>
              <p className="mt-0.5 text-xs text-muted">{LABEL_TEXT[artist.label]}</p>
            </Link>
          </li>
        ))}
      </ul>

      {hiddenCount > 0 && (
        <button
          type="button"
          onClick={() => setShowAll(!showAll)}
          className="mt-6 rounded-full border border-line px-4 py-1.5 text-sm text-body transition-colors hover:border-ink/40"
        >
          {showAll ? "Show fewer" : `Show all ${artists.length}`}
        </button>
      )}
    </div>
  );
}
