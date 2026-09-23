"""Stage 1: collect metadata for every theneedledrop upload into the `videos` table.

Stores title, description, date, duration, type and subject that it works out from the title. 
Never downloads the captions or calls the LLM; uses regex for string parsing.

    uv run collect.py              # all uploads (a few hundred quota units out of 10,000/day)
    uv run collect.py --max 100    # only the newest 100, handy while testing

Safe to rerun: existing rows get fresh metadata, but their pipeline statuses are never touched.
"""

import argparse
import os
import re
from datetime import datetime

import httpx

from db import connect

API = "https://www.googleapis.com/youtube/v3"
CHANNEL_HANDLE = "@theneedledrop"


# --- Pure functions ---
#
# Use pure functions for classify(), parse_subject(), and parse_duration() as these don't rely on API calls, internet, nor a database.
# Makes testing easier as same input generates the same output, and touches nothing outside itself 
# 
# Use impure functions for Youtube API calls to allow the functions to be narrow in scope, and rely on the actual logic
# being inside of the pure functions

def classify(title: str) -> str:
    """Classify video type from its title alone."""
    t = title.upper()

    if "WEEKLY TRACK ROUNDUP" in t:
        return "roundup"
    
    if re.search(r"\bTRACK REVIEWS?\b", t):             # \b: "SOUNDTRACK REVIEW" doesn't count
        return "track_review"
    
    # Using regex to look for either ALBUM, EP, or MIXTAPE adjacent to REVIEW
    if re.search(r"\b(ALBUM|EP|MIXTAPE) REVIEW\b", t):
        return "album_review"
    return "other"


# Extract artist name and album track out of the title string using regex
# i.e SZA - SOS ALBUM REVIEW generates artist SZA, and title SOS
# If title doesn't follow that pattern, that returns None, None
SUBJECT_RE = re.compile(
    # \s* before the dash: older titles have no space ("Tame Impala- Innerspeaker ALBUM REVIEW")
    # \s+ after the dash: required, so "Jay-Z" isn't split in two
    r"^(?P<artist>.+?)\s*[-–]\s+(?P<title>.+?)\s+(?:ALBUM|EP|MIXTAPE|TRACK)\s+REVIEW\b",
    re.IGNORECASE,
)


def parse_subject(title: str) -> tuple[str | None, str | None]:
    """Extracts (artist, title) from a review title; (None, None) if it doesn't fit."""
    m = SUBJECT_RE.match(title.strip())
    if not m:
        return None, None
    return m["artist"].strip(), m["title"].strip()


def parse_duration(iso: str) -> int:
    """YouTube's ISO 8601 video duration format converted to seconds. "PT1H2M3S" -> 3723 seconds."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        raise ValueError(f"unexpected duration: {iso}")
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


# --- YouTube Data API v3 calls ---

def get_uploads_playlist_id(client: httpx.Client) -> str:
    """Youtube prevents scraping an entire channel of videos at once. Instead, every channel
    has a hidden playlist containing all its uploads, newest first. (1 unit)

    This function looks up the ID of the specific playlist for theneedledrop so
    the next function 'iter_video_id_pages) iterate through it. """
    r = client.get("/channels", params={"part": "contentDetails", "forHandle": CHANNEL_HANDLE})
    r.raise_for_status()
    return r.json()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


def iter_video_id_pages(client: httpx.Client, playlist_id: str, max_videos: int | None):
    """Iterates through entire uploads playlist and hands back video IDs in batches of 50
    since YouTube's API caps at 50 results per request"
    
    Yield lists of up to 50 video IDs, following nextPageToken. (1 unit per page)"""
    seen, page_token = 0, None
    while True:
        # Call playlistItems up to 50 items starting from whatever page_token is currently at
        r = client.get("/playlistItems", params={
            "part": "contentDetails", "playlistId": playlist_id,
            "maxResults": 50, "pageToken": page_token,
        })
        r.raise_for_status()
        data = r.json()
        ids = [item["contentDetails"]["videoId"] for item in data["items"]]
        if max_videos is not None:
            ids = ids[: max_videos - seen]
        seen += len(ids)

        # Makes the function a generator: pauses at each yield and hands the caller back 
        # that one page of up to 50 ids rather than having thousands of IDs in memory at once
        yield ids

        # Get's the next page if available otherwise stops the generator as no more pages left or --max limit reached
        page_token = data.get("nextPageToken")
        if not page_token or (max_videos is not None and seen >= max_videos):
            return


def fetch_videos(client: httpx.Client, ids: list[str]) -> list[dict]:
    """Turns video IDs into structured data rows ready to be inserted to database.
    Full title, description, date, and duration for up to 50 videos. (1 unit)"""

    # Calls YouTube's /videos endpoint passing all video IDs into one comma seperated string
    r = client.get("/videos", params={"part": "snippet,contentDetails", "id": ",".join(ids)})

    r.raise_for_status()
    rows = []

    # Iterates through each video object in the response
    for item in r.json()["items"]:
        title = item["snippet"]["title"]
        vtype = classify(title)
        artist, subject = parse_subject(title) if vtype != "roundup" else (None, None)
        rows.append({
            "id": item["id"],
            "title": title,
            "description": item["snippet"]["description"],
            # YouTube gives UTC ("2024-05-01T15:00:07Z"); store it as a plain UTC DATETIME.
            "published_at": datetime.fromisoformat(item["snippet"]["publishedAt"]).replace(tzinfo=None),
            "duration_s": parse_duration(item["contentDetails"]["duration"]),
            "type": vtype,
            "subject_artist": artist,
            "subject_title": subject,
        })
    return rows


# --- Database ---

# Insert new videos; for existing ones refresh metadata only. The *_status and extraction
# columns are deliberately missing from the UPDATE list so a rerun never resets progress
UPSERT_SQL = """
INSERT INTO videos (id, title, description, published_at, duration_s, type, subject_artist, subject_title)
VALUES (%(id)s, %(title)s, %(description)s, %(published_at)s, %(duration_s)s, %(type)s,
        %(subject_artist)s, %(subject_title)s) AS new
ON DUPLICATE KEY UPDATE
  title = new.title, description = new.description, published_at = new.published_at,
  duration_s = new.duration_s, type = new.type,
  subject_artist = new.subject_artist, subject_title = new.subject_title
"""


def main() -> None:
    # Use argparse for reading --max flag to specify videos; defaults to None if not passed (i.e no limit, fetch everything)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max", type=int, default=None, help="only the newest N uploads")
    args = parser.parse_args()

    # Reads API key from .env and puts it in request header
    headers = {"X-goog-api-key": os.environ["YOUTUBE_API_KEY"]}

    # Opens an HTTP client preconfigured to YouTube API endpiont and form database connection from helper
    with httpx.Client(base_url=API, headers=headers, timeout=30) as client, connect() as conn:
        playlist_id = get_uploads_playlist_id(client)
        total = 0

        # Iterate through each of the 50 video ids from generator
        for ids in iter_video_id_pages(client, playlist_id, args.max):
            rows = fetch_videos(client, ids)

            # Write the details from fetched videos inside of videos table
            with conn.cursor() as cur:
                cur.executemany(UPSERT_SQL, rows)
            conn.commit()                       # one commit per page of 50
            total += len(rows)
            print(f"\r{total} videos", end="", flush=True)
        print()

        # Prints summary query (cur is object we send SQL commands to and hands back results using existing network connection formed by conn above)
        with conn.cursor() as cur:
            cur.execute("SELECT type, COUNT(*) AS n FROM videos GROUP BY type ORDER BY n DESC")
            for row in cur.fetchall():
                print(f"  {row['type']:<13} {row['n']}")


if __name__ == "__main__":
    main()
