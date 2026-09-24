"""Stage 2: download YouTube auto-captions for the newest reviews and roundups with timestamps.

Reads: videos rows (type != 'other', captions_status = 'pending')
Writes: data/captions/{video_id}.json and sets captions_status to 'done' or 'failed'

If YouTube starts blocking requests, the script stops and leaves the rest 'pending'.
Wait a while (or switch networks) and rerun; finished videos are skipped.
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

# Sets absolute path to the folder where caption files get saved (fantano/data/captions)
CAPTIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "captions"

# Pause between videos to look less like a bot (Note: 3 seconds was too quick so raised to 10)
PAUSE_S = 10

# Problems with the video itself: retrying won't help, so mark it 'failed' and move on
# Anything else (blocked IP, network trouble) is temporary: stop and leave it 'pending'
PERMANENT_ERRORS = (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, VideoUnplayable, AgeRestricted)

# Get's the newest N videos where captions are still pending
# Recent videos follow the same format of titles, YouTube auto-captions system has gotten more accurate, Can get more videos as Fantano continues to upload
PENDING_SQL = """
SELECT id, title FROM (
  SELECT id, title, captions_status, published_at FROM videos
  WHERE type <> 'other'
  ORDER BY published_at DESC
  LIMIT %s
) AS newest
WHERE captions_status = 'pending'
ORDER BY published_at DESC
"""


def to_lines(snippets: list[dict]) -> list[dict]:
    """Pure function: Library output -> our format: numbered lines the LLM can cite in stage 3.
    
    in:  {'text': 'hi everyone\nfantano here', 'start': 0.0}
    out: {'line': 0, 'start': 0.0, 'text': 'hi everyone fantano here'}

    The LLM can refer to line number whereas we can look up the exact timestamp to ensure accuracy.
    Prevents LLM from hallunicating a timestamp, easier to deal with specific line numbers which are consistent.
    """
    return [
        {"line": i, "start": round(s["start"], 2), "text": " ".join(s["text"].split())}
        for i, s in enumerate(snippets)
    ]


def set_status(conn, video_id: str, status: str) -> None:
    """Not pure (writes to DB): Sets one video to done or failed and commits immediately so progress is saved one video at a time"""
    with conn.cursor() as cur:
        cur.execute("UPDATE videos SET captions_status = %s WHERE id = %s", (status, video_id))
    conn.commit()


def main() -> None:
    """Asks the database which videos need captions, then goes through them one at a time: 
       download, save the file, mark done, wait 3 seconds, repeat"""

    # Reads required --limit CLI flag (--limit X ensures newest 50 have captions; not to download 50 more)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, required=True, help="the newest N reviews/roundups")
    args = parser.parse_args()

    # Ensures output folder exists and creates an instance of the YouTube captions library's client
    CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    api = YouTubeTranscriptApi()

    with connect() as conn:
        # Fetches videos that having pending captions
        with conn.cursor() as cur:
            cur.execute(PENDING_SQL, (args.limit,))
            videos = cur.fetchall()
        print(f"{len(videos)} videos need captions")

        for i, video in enumerate(videos, 1):
            vid = video["id"]

            # Tries to download the video's English captions
            try:
                fetched = api.fetch(vid, languages=["en"])
            # Fails for reason on PERMANENT_ERRORS list then retrying won't fix; marked as failed
            except PERMANENT_ERRORS as e:
                print(f"[{i}/{len(videos)}] FAILED  {vid}  {type(e).__name__}  {video['title']}")
                set_status(conn, vid, "failed")
                continue
            # Any other exception (i.e network problems, YouTube blocking IP) requires retrying later
            except Exception as e:
                print(f"[{i}/{len(videos)}] STOPPED {vid}  {type(e).__name__}: YouTube may be blocking us.")
                print("Nothing is lost: rerun later and it resumes from here.")
                sys.exit(1)

            # Convert to raw data to clean numbered lines and write JSON to disk
            lines = to_lines(fetched.to_raw_data())
            path = CAPTIONS_DIR / f"{vid}.json"
            path.write_text(json.dumps(lines, ensure_ascii=False, indent=0))

            # Only after the file is safely on disk
            set_status(conn, vid, "done")          
            print(f"[{i}/{len(videos)}] ok      {vid}  {len(lines)} lines  {video['title']}")
            time.sleep(PAUSE_S)


if __name__ == "__main__":
    main()
