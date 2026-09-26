"use client";

/**
 * the review box under the artist's photo. it shows one review at a time, newest first, and
 * the ‹ › arrows step through the rest ("2 / 6"). each review shows:
 *   - the album or song title, the kind, and his score
 *   - the AI summary (never in quotation marks, it's not his words)
 *   - one real quote in quotation marks, with ▶ Watch @ m:ss
 *
 * a review whose captions haven't been through the ai yet has no summary or quote, so it shows
 * his fav tracks from the description and "▶ Watch the review" instead. once the captions
 * arrive, the pipeline upgrades the review and the summary + quote replace them automatically.
 *
 * usage:
 *   <ReviewCarousel reviews={reviews} />   // reviews from getReviews(), newest first
 */

import { useState } from "react";

import WatchLink from "@/components/WatchLink";
import type { Review } from "@/lib/types";

const KIND_TEXT = { album: "Album", ep: "EP", mixtape: "Mixtape" } as const;

export default function ReviewCarousel({ reviews }: { reviews: Review[] }) {
  const [index, setIndex] = useState(0);
  const review = reviews[index];
  const hasSeveral = reviews.length > 1;

  // wraps around: going back from the first review shows the last one
  function step(direction: 1 | -1) {
    setIndex((current) => (current + direction + reviews.length) % reviews.length);
  }

  return (
    <section aria-label="His reviews" className="rounded-2xl border border-line p-5">
      <div aria-live="polite">
        <div className="flex items-baseline justify-between gap-3">
          <p className="min-w-0 truncate font-semibold text-ink" title={review.title}>
            {review.title}
          </p>
          {review.score_text && <span className="shrink-0 text-sm font-medium text-ink">{review.score_text}</span>}
        </div>
        <p className="mt-0.5 text-xs text-muted">{review.kind ? KIND_TEXT[review.kind] : "Track"} review</p>

        {review.summary && <p className="mt-4 text-[15px] leading-relaxed text-body">{review.summary}</p>}

        {!review.summary && review.fav_tracks.length > 0 && (
          <p className="mt-4 text-[15px] leading-relaxed text-body">
            <span className="text-muted">Fav tracks: </span>
            {review.fav_tracks.join(", ")}
          </p>
        )}

        {review.quote && (
          <figure className="mt-4 border-l-2 border-line pl-4">
            <blockquote className="text-[15px] leading-relaxed text-ink">“{review.quote}”</blockquote>
            <figcaption className="mt-2">
              <WatchLink videoId={review.video_id} startSeconds={review.quote_start_s} />
            </figcaption>
          </figure>
        )}

        {!review.quote && (
          <div className="mt-4">
            <WatchLink videoId={review.video_id} startSeconds={null} label="Watch the review" />
          </div>
        )}
      </div>

      {hasSeveral && (
        <div className="mt-5 flex items-center justify-between border-t border-line pt-4">
          <ArrowButton label="Newer review" onClick={() => step(-1)}>‹</ArrowButton>
          <span className="text-xs text-muted tabular-nums">
            {index + 1} / {reviews.length}
          </span>
          <ArrowButton label="Older review" onClick={() => step(1)}>›</ArrowButton>
        </div>
      )}
    </section>
  );
}

function ArrowButton({ label, onClick, children }: { label: string; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="flex size-8 items-center justify-center rounded-full border border-line text-lg leading-none text-ink transition-colors hover:border-ink/40"
    >
      {children}
    </button>
  );
}
