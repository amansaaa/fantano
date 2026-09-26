"""stage 1: collect. saves the metadata for every theneedledrop upload into the videos table.

for each upload it stores the title, description, publish date, and duration from the YouTube
Data API, plus two things it works out from the title with plain regex (no ai):
  - the type: album_review, track_review, roundup, or other
  - the subject: "SZA - SOS ALBUM REVIEW" -> artist "SZA", title "SOS"

it doesn't download captions or call the ai, those are later stages. metadata for every
upload only costs a few hundred of the 10,000 free daily quota units, so we grab it all.

usage:
    uv run collect.py              # every upload on the channel
    uv run collect.py --max 100    # only the newest 100, handy while testing

safe to rerun: existing rows get fresh metadata, but their pipeline statuses are never touched.
"""

import argparse
import os
import re
from datetime import datetime

import httpx

from db import connect

YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3"
CHANNEL_HANDLE = "@theneedledrop"

# the api never returns more than 50 items per request
PAGE_SIZE = 50


# --- reading facts from a title ---
# these are pure functions: same input title generates the same answer out with no internet or database involved.
# that makes them easy to test, and it keeps the api functions below thin

def classify_title(title: str) -> str:
    """works out the video type from its title alone: album_review, track_review, roundup, or other.
    the order of the checks matters, because a roundup title contains the word "track" too."""
    upper_title = title.upper()

    if "WEEKLY TRACK ROUNDUP" in upper_title:
        return "roundup"

    # \b means a word boundary, so "SOUNDTRACK REVIEW" doesn't count as a track review
    if re.search(r"\bTRACK REVIEWS?\b", upper_title):
        return "track_review"

    if re.search(r"\b(ALBUM|EP|MIXTAPE) REVIEW\b", upper_title):
        return "album_review"

    return "other"


# "SZA - SOS ALBUM REVIEW" -> artist "SZA", title "SOS"
#   \s* before the dash: older titles have no space there ("Tame Impala- Innerspeaker ALBUM REVIEW")
#   \s+ after the dash: required, so the dash inside "Jay-Z" doesn't split his name in two
SUBJECT_PATTERN = re.compile(
    r"^(?P<artist>.+?)\s*[-–]\s+(?P<title>.+?)\s+(?:ALBUM|EP|MIXTAPE|TRACK)\s+REVIEW\b",
    re.IGNORECASE,
)


def parse_subject(title: str) -> tuple[str | None, str | None]:
    """pulls (artist, release title) out of a review title, e.g.
    "SZA - SOS ALBUM REVIEW" -> ("SZA", "SOS").

    returns (None, None) when the title doesn't fit the pattern. that's only ~20 of 3,600+
    reviews, and stage 3 skips those instead of guessing."""
    match = SUBJECT_PATTERN.match(title.strip())
    if not match:
        return None, None
    return match["artist"].strip(), match["title"].strip()


def parse_duration(iso_duration: str) -> int:
    """turns YouTube's ISO 8601 duration into seconds, e.g. "PT1H2M3S" -> 3723.
    every part is optional, so "PT45S" and "P0D" work too."""
    match = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
    if not match:
        raise ValueError(f"unexpected duration: {iso_duration}")

    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


# --- talking to the YouTube Data API ---

def get_uploads_playlist_id(client: httpx.Client) -> str:
    """finds the channel's hidden "uploads" playlist, which holds every video it has posted, newest first.
    the api has no cheap "list every video on this channel" call, so walking
    this playlist is the standard way to do it. costs 1 quota unit."""
    response = client.get("/channels", params={"part": "contentDetails", "forHandle": CHANNEL_HANDLE})
    response.raise_for_status()
    channel = response.json()["items"][0]
    return channel["contentDetails"]["relatedPlaylists"]["uploads"]


def iterate_video_id_pages(client: httpx.Client, playlist_id: str, max_videos: int | None):
    """walks the uploads playlist one page at a time and yields each page's video ids
    (up to 50). stops when there are no pages left, or once max_videos ids have been handed out.
    costs 1 quota unit per page.

    it's a generator, so the caller can save each page as soon as it arrives instead of
    waiting for thousands of ids to pile up in memory."""
    ids_so_far = 0
    page_token = None  # None means "start from the first page"

    while True:
        response = client.get("/playlistItems", params={
            "part": "contentDetails",
            "playlistId": playlist_id,
            "maxResults": PAGE_SIZE,
            "pageToken": page_token,
        })
        response.raise_for_status()
        page = response.json()

        video_ids = [item["contentDetails"]["videoId"] for item in page["items"]]
        if max_videos is not None:
            # trim the last page so we hand out exactly max_videos ids in total
            video_ids = video_ids[:max_videos - ids_so_far]
        ids_so_far += len(video_ids)

        yield video_ids

        page_token = page.get("nextPageToken")
        reached_max = max_videos is not None and ids_so_far >= max_videos
        if not page_token or reached_max:
            return


def fetch_video_rows(client: httpx.Client, video_ids: list[str]) -> list[dict]:
    """gets the full details for up to 50 videos in one call and turns each one into a row
    that's ready for the videos table. playlist items only carry a short description and no
    duration, which is why this second call is needed. costs 1 quota unit."""
    response = client.get("/videos", params={"part": "snippet,contentDetails", "id": ",".join(video_ids)})
    response.raise_for_status()

    rows = []
    for video in response.json()["items"]:
        title = video["snippet"]["title"]
        video_type = classify_title(title)

        # roundups cover lots of artists, so there's no single subject to pull out
        if video_type == "roundup":
            subject_artist, subject_title = None, None
        else:
            subject_artist, subject_title = parse_subject(title)

        # YouTube gives utc like "2024-05-01T15:00:07Z". we store it as a plain utc DATETIME
        published_at = datetime.fromisoformat(video["snippet"]["publishedAt"]).replace(tzinfo=None)

        rows.append({
            "id": video["id"],
            "title": title,
            "description": video["snippet"]["description"],
            "published_at": published_at,
            "duration_s": parse_duration(video["contentDetails"]["duration"]),
            "type": video_type,
            "subject_artist": subject_artist,
            "subject_title": subject_title,
        })
    return rows


# --- saving to the database ---

# insert new videos, and for ones we already have, refresh the metadata only.
# the *_status and extraction columns are left out of the UPDATE list on purpose,
# so rerunning this never resets progress made by the later stages
UPSERT_VIDEO_SQL = """
INSERT INTO videos (id, title, description, published_at, duration_s, type, subject_artist, subject_title)
VALUES (%(id)s, %(title)s, %(description)s, %(published_at)s, %(duration_s)s, %(type)s,
        %(subject_artist)s, %(subject_title)s) AS new
ON DUPLICATE KEY UPDATE
  title = new.title, description = new.description, published_at = new.published_at,
  duration_s = new.duration_s, type = new.type,
  subject_artist = new.subject_artist, subject_title = new.subject_title
"""


def save_video_rows(conn, rows: list[dict]) -> None:
    """upserts one page of rows and commits, so a crash on page 40 still keeps pages 1-39."""
    with conn.cursor() as cur:
        cur.executemany(UPSERT_VIDEO_SQL, rows)
    conn.commit()


def print_type_counts(conn) -> None:
    """prints how many videos of each type are in the table, as a quick sanity check."""
    with conn.cursor() as cur:
        cur.execute("SELECT type, COUNT(*) AS count FROM videos GROUP BY type ORDER BY count DESC")
        for row in cur.fetchall():
            print(f"  {row['type']:<13} {row['count']}")


# --- running the stage ---

def parse_args() -> argparse.Namespace:
    """reads the optional --max flag. without it, every upload gets collected."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max", type=int, default=None, help="only the newest N uploads")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # the key goes in a header, not the url, so it never shows up in error messages or logs.
    # .env is already loaded because importing db.py loads it
    headers = {"X-goog-api-key": os.environ["YOUTUBE_API_KEY"]}

    # timeout=30 so one stuck request can't hang the whole run forever
    with httpx.Client(base_url=YOUTUBE_API_URL, headers=headers, timeout=30) as client, connect() as conn:
        playlist_id = get_uploads_playlist_id(client)

        videos_saved = 0
        for video_ids in iterate_video_id_pages(client, playlist_id, args.max):
            rows = fetch_video_rows(client, video_ids)
            save_video_rows(conn, rows)
            videos_saved += len(rows)
            print(f"\r{videos_saved} videos", end="", flush=True)
        print()

        print_type_counts(conn)


if __name__ == "__main__":
    main()
