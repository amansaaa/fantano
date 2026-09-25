"""stage 2: captions. downloads YouTube's auto-generated captions for the newest reviews and roundups.

each video's captions get saved as a list of numbered lines, each with its start time:

    data/captions/{id}.json
    [{"line": 44, "start": 190.2, "text": "which honestly gives me some frank ocean"}, ...]

those line numbers are what the ai cites in stage 3. code then looks up the real start time
from the line, so the ai never has to come up with a timestamp.

usage:
    uv run captions.py --limit 50     # make sure the newest 50 reviews and roundups have captions

reads:   videos rows (type isn't 'other', captions_status = 'pending')
writes:  data/captions/{id}.json, and sets captions_status to 'done' or 'failed'

if YouTube starts blocking requests, the script stops and leaves the rest 'pending'.
wait a while (or switch networks) and rerun. finished videos are skipped.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from youtube_transcript_api import (
    AgeRestricted,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeTranscriptApi,
)

from db import connect

# fantano/data/captions, found relative to this file so it works from any folder
CAPTIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "captions"

# pause between videos so we look less like a bot. 3 seconds got us blocked after ~20 videos
PAUSE_SECONDS = 10

# problems with the video itself (captions turned off, video deleted...). retrying won't help,
# so the video gets marked 'failed' and we move on. anything else (a blocked ip, network
# trouble) is temporary, so we stop and leave it 'pending' for the next run
PERMANENT_ERRORS = (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, VideoUnplayable, AgeRestricted)

# the newest N reviews and roundups first, then only the ones still pending among them.
# so --limit 50 means "make sure the newest 50 have captions", not "download 50 more".
# newest first because recent videos share one title/description format and have better captions
PENDING_VIDEOS_SQL = """
SELECT id, title FROM (
  SELECT id, title, captions_status, published_at FROM videos
  WHERE type <> 'other'
  ORDER BY published_at DESC
  LIMIT %s
) AS newest
WHERE captions_status = 'pending'
ORDER BY published_at DESC
"""


def to_caption_lines(snippets: list[dict]) -> list[dict]:
    """turns the caption library's output into our format: numbered lines with a start time and
    cleaned-up text. pure function, no network involved.

        in:   {"text": "hi everyone\\nfantano here", "start": 0.0, "duration": 3.1}
        out:  {"line": 0, "start": 0.0, "text": "hi everyone fantano here"}
    """
    caption_lines = []
    for line_number, snippet in enumerate(snippets):
        # squash newlines and double spaces inside a caption into single spaces
        clean_text = " ".join(snippet["text"].split())
        caption_lines.append({"line": line_number, "start": round(snippet["start"], 2), "text": clean_text})
    return caption_lines


def save_caption_file(video_id: str, caption_lines: list[dict]) -> None:
    """writes the caption lines to data/captions/{id}.json. ensure_ascii=False keeps names
    like "Björk" readable in the file."""
    caption_file = CAPTIONS_DIR / f"{video_id}.json"
    caption_file.write_text(json.dumps(caption_lines, ensure_ascii=False, indent=0))


def save_status(conn, video_id: str, status: str) -> None:
    """sets one video's captions_status to 'done' or 'failed' and commits right away, so
    progress is saved one video at a time."""
    with conn.cursor() as cur:
        cur.execute("UPDATE videos SET captions_status = %s WHERE id = %s", (status, video_id))
    conn.commit()


def parse_args() -> argparse.Namespace:
    """reads the required --limit flag."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, required=True, help="the newest N reviews and roundups")
    return parser.parse_args()


def fetch_pending_videos(conn, limit: int) -> list[dict]:
    """the videos among the newest `limit` reviews and roundups that still need captions."""
    with conn.cursor() as cur:
        cur.execute(PENDING_VIDEOS_SQL, (limit,))
        return cur.fetchall()


def main() -> None:
    args = parse_args()
    CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    transcript_api = YouTubeTranscriptApi()

    with connect() as conn:
        videos = fetch_pending_videos(conn, args.limit)
        print(f"{len(videos)} videos need captions")

        for position, video in enumerate(videos, start=1):
            video_id = video["id"]
            progress = f"[{position}/{len(videos)}]"

            try:
                transcript = transcript_api.fetch(video_id, languages=["en"])
            except PERMANENT_ERRORS as error:
                # the video's fault, retrying won't fix it
                print(f"{progress} FAILED  {video_id}  {type(error).__name__}  {video['title']}")
                save_status(conn, video_id, "failed")
                continue
            except Exception as error:
                # most likely YouTube blocking our ip. stop everything and leave the rest pending
                print(f"{progress} STOPPED {video_id}  {type(error).__name__}: YouTube may be blocking us.")
                print("nothing is lost: rerun later and it picks up from here.")
                sys.exit(1)

            caption_lines = to_caption_lines(transcript.to_raw_data())
            save_caption_file(video_id, caption_lines)
            # mark it done only after the file is safely on disk. if we crash in between, the
            # video is still pending and just gets downloaded again next time
            save_status(conn, video_id, "done")
            print(f"{progress} ok      {video_id}  {len(caption_lines)} lines  {video['title']}")

            time.sleep(PAUSE_SECONDS)


if __name__ == "__main__":
    main()
