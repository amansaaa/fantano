/**
 * turning a video id + a second in the video into the "▶ Watch @ 3:10" text and link.
 * pure functions, no database, so they're tested in tests/youtube.test.ts.
 */

// the link starts a few seconds early so you hear the lead-in, not a cut-off word
const LEAD_IN_SECONDS = 5;
const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_HOUR = 3600;

/**
 * seconds -> the clock text youtube shows.
 *
 *   formatTime(190)  -> "3:10"
 *   formatTime(5)    -> "0:05"
 *   formatTime(3725) -> "1:02:05"
 */
export function formatTime(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / SECONDS_PER_HOUR);
  const minutes = Math.floor((totalSeconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  const seconds = Math.floor(totalSeconds % SECONDS_PER_MINUTE);
  const paddedSeconds = String(seconds).padStart(2, "0");
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${paddedSeconds}`;
  }
  return `${minutes}:${paddedSeconds}`;
}

/**
 * the youtube link that jumps to just before he said it. no time -> the start of the video.
 *
 *   watchUrl("abc123XYZ00", 190)  -> "https://www.youtube.com/watch?v=abc123XYZ00&t=185s"
 *   watchUrl("abc123XYZ00", 2)    -> "https://www.youtube.com/watch?v=abc123XYZ00&t=0s"
 *   watchUrl("abc123XYZ00", null) -> "https://www.youtube.com/watch?v=abc123XYZ00"
 */
export function watchUrl(videoId: string, startSeconds: number | null): string {
  const url = `https://www.youtube.com/watch?v=${videoId}`;
  if (startSeconds === null) {
    return url;
  }
  return `${url}&t=${Math.max(0, startSeconds - LEAD_IN_SECONDS)}s`;
}
