/**
 * the dark red "▶ Watch @ 3:47 — {video title} ↗" link that proves a quote. it opens youtube
 * in a new tab, a few seconds before he says it.
 *
 * usage:
 *   <WatchLink videoId="abc123XYZ00" startSeconds={227} videoTitle="SZA - SOS ALBUM REVIEW" />
 *   -> ▶ Watch @ 3:47 — SZA - SOS ALBUM REVIEW ↗
 *   <WatchLink videoId="abc123XYZ00" startSeconds={null} />
 *   -> ▶ Watch ↗   (he never said it aloud, so it opens the video from the start)
 *   <WatchLink videoId="abc123XYZ00" startSeconds={null} label="Watch the review" />
 *   -> ▶ Watch the review ↗
 */

import { formatTime, watchUrl } from "@/lib/youtube";

type Props = {
  videoId: string;
  startSeconds: number | null;
  videoTitle?: string;
  label?: string;
};

export default function WatchLink({ videoId, startSeconds, videoTitle, label = "Watch" }: Props) {
  const time = startSeconds === null ? "" : ` @ ${formatTime(startSeconds)}`;
  return (
    <a
      href={watchUrl(videoId, startSeconds)}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex max-w-full items-baseline gap-1 text-sm text-watch underline-offset-4 hover:underline"
    >
      <span className="shrink-0">▶ {label}{time}</span>
      {videoTitle && <span className="truncate">— {videoTitle}</span>}
      <span aria-hidden className="shrink-0">↗</span>
    </a>
  );
}
