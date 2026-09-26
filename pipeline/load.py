"""stage 4: match names + load. turns each video's verified extraction into real database rows.

until now every artist is just a string ("Frank Ocean", "frank ocean", "Bjork"). this stage
decides which strings are the same real artist, gives each one a single artists row, and then
writes the reviews, connections, and recommended songs that point at those rows.

where a name came from decides how much we trust it:
  - written names (the review title, the roundup track lists in the description) are typed by
    fantano's team, so they're used as-is
  - spoken names (the artists in connections) come from auto-captions + the ai, so they have
    to pass the matching rule first:
      1. it matches an artist he has reviewed (fuzzy, >= 95), or
      2. exactly one MusicBrainz artist has that name, and it's a clear winner
      otherwise the name is dropped and logged, never guessed

for every extracted video, this script:
  1. deletes any rows this video wrote before, so reloading a video never duplicates anything
  2. finds or adds the artists, releases, and tracks it mentions (never two rows for one thing)
  3. writes the review, the connections, and the endorsements (the songs he liked)
  4. commits the whole video at once, or nothing if anything fails

usage:
    uv run load.py                    # every extracted video that isn't loaded yet
    uv run load.py --video Zt2esoyoTgs    # reload one video, handy for testing
    uv run load.py --reload           # reload everything, e.g. after changing the matching rule

reads:   videos.extraction (from extract.py) and every reviewed artist name in videos
writes:  artists, releases, tracks, reviews, connections, endorsements (MySQL)
         data/musicbrainz/{name_key}.json   raw MusicBrainz search results, reused on reruns
         data/logs/dropped_names/{id}.json  every spoken name that didn't match, and why
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
from rapidfuzz import fuzz, process

from db import connect
from description import split_track_line
from extract import to_title_key

# where everything lives on disk
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MUSICBRAINZ_CACHE_DIR = DATA_DIR / "musicbrainz"
DROPPED_NAMES_DIR = DATA_DIR / "logs" / "dropped_names"

# rule 1: how close a spoken name has to be to a reviewed artist's name (0-100).
# 90 was too loose on real data: "The Velvet Underground" matched "The Velvet Underground & Nico"
REVIEWED_MATCH_THRESHOLD = 95

# rule 2: MusicBrainz
MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2/artist"
MUSICBRAINZ_RESULTS = 5
# a result only counts if its name (or one of its aliases) is basically what he said
MUSICBRAINZ_NAME_THRESHOLD = 90
# musicbrainz's own 0-100 search score for the best result, and how far ahead of the next
# same-named artist it has to be. two bands both called "Repentance" at 100 and 97 -> dropped
MUSICBRAINZ_MIN_SCORE = 95
MUSICBRAINZ_MIN_LEAD = 10
# musicbrainz allows 1 request per second, so wait a bit longer than that between searches
MUSICBRAINZ_PAUSE_SECONDS = 1.1
MUSICBRAINZ_MAX_ATTEMPTS = 3
REQUEST_TIMEOUT_SECONDS = 30
PLACEHOLDER_CONTACT = "you@example.com"


# --- picking which videos to work on ---

# extract.py already decided which videos are in scope, so this is just "extracted, not loaded yet"
PENDING_VIDEOS_SQL = """
SELECT id, title, type, extraction FROM videos
WHERE extract_status = 'done' AND load_status = 'pending'
ORDER BY published_at DESC
"""

# --reload redoes every extracted video, loaded or not
ALL_EXTRACTED_VIDEOS_SQL = """
SELECT id, title, type, extraction FROM videos
WHERE extract_status = 'done'
ORDER BY published_at DESC
"""

# --video skips the status filter on purpose, so you can redo one video while testing
SINGLE_VIDEO_SQL = """
SELECT id, title, type, extraction FROM videos WHERE id = %s AND extract_status = 'done'
"""

# the artist of every review title, across all 5,000+ videos (not just the loaded ones).
# this is rule 1's list: if he reviewed you, a spoken name that matches you is trusted
REVIEWED_ARTISTS_SQL = """
SELECT DISTINCT subject_artist FROM videos
WHERE type IN ('album_review', 'track_review') AND subject_artist IS NOT NULL
"""


# --- names -> keys ---

def to_name_key(name: str) -> str:
    """the spelling-proof version of a name, used to spot the same artist written two ways.
    lowercase, no accents, no spaces or punctuation, and "$" counts as "s":

        "A$AP Rocky" -> "asaprocky"      "ASAP Rocky" -> "asaprocky"
        "Björk"      -> "bjork"          "D.R.A.M."   -> "dram"
    """
    # swap "$" before normalizing, because normalizing throws it away as punctuation
    return to_title_key(name.replace("$", "s"))


# --- rule 1: artists he reviewed ---

def find_reviewed_match(spoken_name: str, reviewed_names: list[str], reviewed_keys: list[str]) -> str | None:
    """the reviewed artist this spoken name belongs to, spelled the way the review title spells
    it, or None if nobody is close enough:

        "Bjork"       -> "Björk"
        "Schoolboy Q" -> "ScHoolboy Q"
        "The Velvet Underground" -> None  (the closest is "... & Nico", only 91)

    reviewed_keys has to line up with reviewed_names (reviewed_keys[i] is the key of
    reviewed_names[i]). they're computed once per run instead of once per name.
    """
    best_match = process.extractOne(
        to_name_key(spoken_name), reviewed_keys, scorer=fuzz.ratio, score_cutoff=REVIEWED_MATCH_THRESHOLD
    )
    if best_match is None:
        return None
    # extractOne gives back (key, score, position in the list)
    matched_position = best_match[2]
    return reviewed_names[matched_position]


# --- rule 2: MusicBrainz ---

def build_user_agent() -> str:
    """musicbrainz blocks requests without a User-Agent that says who's asking and how to
    reach them, so the contact comes from MUSICBRAINZ_CONTACT in .env."""
    contact = os.environ.get("MUSICBRAINZ_CONTACT", "")
    if not contact or contact == PLACEHOLDER_CONTACT:
        sys.exit("set MUSICBRAINZ_CONTACT in .env (your email or the repo url) before running load.py")
    return f"fantano/0.1 ( {contact} )"


def search_musicbrainz(name: str, user_agent: str) -> list[dict]:
    """the top musicbrainz artists named like `name`, best first. each result looks like
    {"id": "<mbid>", "name": "Nick Cave", "score": 100, "aliases": [{"name": "Nicholas Edward Cave"}, ...]}.

    results are saved in data/musicbrainz/{name_key}.json, so a rerun never asks twice for the
    same name (and never waits on the rate limit for it). raises httpx.HTTPError if musicbrainz
    keeps failing, which stops the run, same as a Gemini outage stops extract.py.
    """
    cache_file = MUSICBRAINZ_CACHE_DIR / f"{to_name_key(name)}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())["artists"]

    # artist:"..." searches the name field only, as one phrase, so "Cold" doesn't pull in
    # "Coldplay". the quotes inside the name get escaped so they can't break the query
    escaped_name = name.replace('"', '\\"')
    params = {"query": f'artist:"{escaped_name}"', "fmt": "json", "limit": MUSICBRAINZ_RESULTS}
    headers = {"User-Agent": user_agent}

    for attempt in range(1, MUSICBRAINZ_MAX_ATTEMPTS + 1):
        time.sleep(MUSICBRAINZ_PAUSE_SECONDS)
        response = httpx.get(MUSICBRAINZ_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        # 503 is musicbrainz saying "slow down". wait longer each time and try again
        if response.status_code == 503 and attempt < MUSICBRAINZ_MAX_ATTEMPTS:
            time.sleep(attempt * 5)
            continue
        response.raise_for_status()
        cache_file.write_text(response.text)
        return response.json()["artists"]

    # the loop always returns or raises, this just keeps type checkers happy
    raise httpx.HTTPError("musicbrainz kept failing")


def is_named_like(spoken_name: str, musicbrainz_artist: dict) -> bool:
    """is this musicbrainz artist actually called what he said? checks the official name and
    every alias, since people say the name they know:

        "Nick Cave" vs Nick Cave                       -> True
        "Jorge Ben" vs Jorge Ben Jor (alias Jorge Ben)  -> True
        "Cold"      vs Cold Chisel                     -> False
    """
    spoken_key = to_name_key(spoken_name)
    names_to_check = [musicbrainz_artist["name"]]
    for alias in musicbrainz_artist.get("aliases", []):
        names_to_check.append(alias["name"])

    for candidate_name in names_to_check:
        if fuzz.ratio(spoken_key, to_name_key(candidate_name)) >= MUSICBRAINZ_NAME_THRESHOLD:
            return True
    return False


def pick_musicbrainz_artist(spoken_name: str, results: list[dict]) -> tuple[dict | None, str | None]:
    """applies rule 2 to one search: keep only the results named like what he said, then
    accept the best one if it scores >= 95 and is >= 10 points ahead of the next one.

    returns ({"name": official name, "mbid": id}, None) when accepted, or (None, reason):

        "Nick Cave"  -> Nick Cave. "Nick Cave & the Bad Seeds" isn't named like it, so it's no rival
        "Repentance" -> None, two bands called Repentance at 100 and 97 is a coin flip
        "Cold"       -> None, the only real "Cold" scores 94 (the top hit was Cold Chisel)
    """
    named_like = []
    for result in results:
        if is_named_like(spoken_name, result):
            named_like.append(result)
    if not named_like:
        return None, "no musicbrainz artist with that name"

    named_like.sort(key=lambda result: result["score"], reverse=True)
    best = named_like[0]
    if best["score"] < MUSICBRAINZ_MIN_SCORE:
        return None, f"best musicbrainz match only scores {best['score']}"

    if len(named_like) > 1:
        runner_up = named_like[1]
        if best["score"] - runner_up["score"] < MUSICBRAINZ_MIN_LEAD:
            return None, f"{len(named_like)} musicbrainz artists named like this, no clear winner"

    return {"name": best["name"], "mbid": best["id"]}, None


# --- the whole rule for one spoken name ---

class NameMatcher:
    """holds what matching needs for a whole run (the reviewed list and the User-Agent), so
    each lookup is just matcher.match("Frank Ocean")."""

    def __init__(self, reviewed_names: list[str], user_agent: str):
        self.reviewed_names = reviewed_names
        self.reviewed_keys = [to_name_key(name) for name in reviewed_names]
        self.user_agent = user_agent

    def match(self, spoken_name: str) -> tuple[dict | None, str | None]:
        """returns ({"name": ..., "mbid": ... or None}, None) for a kept name, or (None, reason)
        for a dropped one. rule 1 first because it's free and it's his own vocabulary."""
        if not to_name_key(spoken_name):
            return None, "name has no letters or digits"

        reviewed_name = find_reviewed_match(spoken_name, self.reviewed_names, self.reviewed_keys)
        if reviewed_name:
            return {"name": reviewed_name, "mbid": None}, None

        results = search_musicbrainz(spoken_name, self.user_agent)
        return pick_musicbrainz_artist(spoken_name, results)


# --- finding or adding rows (never two rows for the same thing) ---

def find_or_add_artist(cur, name: str, mbid: str | None = None) -> int:
    """the artists.id for this artist, adding a row only if it's really new.

    looks up by mbid first (the real identity), then by name_key, so "ASAP Rocky" finds the
    row that "A$AP Rocky" made. if a name_key match has no mbid yet and we just learned it,
    it gets saved on that row.
    """
    if mbid:
        cur.execute("SELECT id FROM artists WHERE mbid = %s", (mbid,))
        row = cur.fetchone()
        if row:
            return row["id"]

    name_key = to_name_key(name)
    cur.execute("SELECT id, mbid FROM artists WHERE name_key = %s LIMIT 1", (name_key,))
    row = cur.fetchone()
    if row:
        if mbid and row["mbid"] is None:
            cur.execute("UPDATE artists SET mbid = %s WHERE id = %s", (mbid, row["id"]))
        return row["id"]

    cur.execute("INSERT INTO artists (name, name_key, mbid) VALUES (%s, %s, %s)", (name, name_key, mbid))
    return cur.lastrowid


def mark_reviewed(cur, artist_id: int) -> None:
    """flags an artist as reviewed, which is what makes them show up in search."""
    cur.execute("UPDATE artists SET is_reviewed = TRUE WHERE id = %s", (artist_id,))


def find_or_add_release(cur, artist_id: int, title: str, kind: str) -> int:
    """the releases.id for this artist's album/ep/mixtape. the same album reviewed twice
    (say, a re-review) lands on one row, matched by title_key."""
    title_key = to_title_key(title)
    cur.execute("SELECT id FROM releases WHERE artist_id = %s AND title_key = %s", (artist_id, title_key))
    row = cur.fetchone()
    if row:
        return row["id"]

    cur.execute(
        "INSERT INTO releases (artist_id, title, title_key, kind) VALUES (%s, %s, %s, %s)",
        (artist_id, title, title_key, kind),
    )
    return cur.lastrowid


def find_or_add_track(cur, artist_id: int, title: str) -> int:
    """the tracks.id for this artist's song. "Red Lights" and "REDLIGHTS" are one row."""
    title_key = to_title_key(title)
    cur.execute("SELECT id FROM tracks WHERE artist_id = %s AND title_key = %s", (artist_id, title_key))
    row = cur.fetchone()
    if row:
        return row["id"]

    cur.execute(
        "INSERT INTO tracks (artist_id, title, title_key) VALUES (%s, %s, %s)",
        (artist_id, title, title_key),
    )
    return cur.lastrowid


# --- writing a video's rows ---

def delete_video_rows(cur, video_id: str) -> None:
    """removes everything this video wrote on an earlier run, so loading it again starts clean.
    artists, releases, and tracks stay, since other videos may point at them too."""
    for table in ["endorsements", "connections", "reviews"]:
        # the table name is from the fixed list above, never from outside input
        cur.execute(f"DELETE FROM {table} WHERE video_id = %s", (video_id,))


def add_connection(cur, video_id: str, from_artist_id: int, to_artist_id: int, label: str,
                   quote: str | None = None, start_s: int | None = None) -> None:
    """writes one "fantano linked A to B" row."""
    cur.execute(
        "INSERT INTO connections (video_id, from_artist_id, to_artist_id, label, quote, start_s) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (video_id, from_artist_id, to_artist_id, label, quote, start_s),
    )


def add_endorsement(cur, video_id: str, track_id: int, source: str, take: dict | None) -> None:
    """writes one "songs he liked" row. take is his quote + summary about the song, or None if
    he never talked about it aloud (the row still counts, it just has no ▶ link)."""
    summary = take["summary"] if take else None
    quote = take["quote"] if take else None
    start_s = take["start_s"] if take else None
    cur.execute(
        "INSERT INTO endorsements (track_id, video_id, source, summary, quote, start_s) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (track_id, video_id, source, summary, quote, start_s),
    )


def add_spoken_connections(cur, video_id: str, connections: list[dict], from_artist_ids: dict[str, int],
                           matcher: NameMatcher) -> tuple[int, list[dict]]:
    """runs every spoken connection through the name rule and writes the ones that pass.

    from_artist_ids maps each connection's about_artist (the artist being discussed) to their
    artists.id. returns (how many were written, the dropped ones with a reason).
    """
    written_count = 0
    dropped_names = []

    for connection in connections:
        matched_artist, reason = matcher.match(connection["artist"])
        if matched_artist is None:
            dropped_names.append({"name": connection["artist"], "heard_as": connection["heard_as"], "reason": reason})
            continue

        from_artist_id = from_artist_ids[connection["about_artist"]]
        to_artist_id = find_or_add_artist(cur, matched_artist["name"], matched_artist["mbid"])
        # the name matched the artist being discussed after all (the schema would reject this row anyway)
        if to_artist_id == from_artist_id:
            dropped_names.append({"name": connection["artist"], "heard_as": connection["heard_as"],
                                  "reason": f"matched the artist being discussed ({matched_artist['name']})"})
            continue

        add_connection(cur, video_id, from_artist_id, to_artist_id, connection["label"],
                       connection["quote"], connection["start_s"])
        written_count += 1

    return written_count, dropped_names


def add_collaborators(cur, video_id: str, artist_id: int, featured_names: list[str]) -> int:
    """the "ft." artists on a track become collaborator connections. they come from the
    written credits, not speech, so there's no quote or timestamp. returns how many were written."""
    written_count = 0
    for featured_name in featured_names:
        featured_artist_id = find_or_add_artist(cur, featured_name)
        if featured_artist_id == artist_id:
            continue
        add_connection(cur, video_id, artist_id, featured_artist_id, "collaborator")
        written_count += 1
    return written_count


def load_review(cur, video_id: str, extraction: dict, matcher: NameMatcher) -> tuple[str, list[dict]]:
    """writes an album or track review: the review itself, the songs he liked, and the
    connections. returns (a short summary for the progress line, the dropped names)."""
    artist_id = find_or_add_artist(cur, extraction["artist"])
    mark_reviewed(cur, artist_id)

    pull_quote = extraction["pull_quote"] or {}
    release_id = None
    track_id = None
    endorsement_count = 0
    collaborator_count = 0

    if extraction["kind"] == "track":
        # a track review title can carry credits: "Song ft. Someone"
        track_parts = split_track_line(f"{extraction['artist']} - {extraction['title']}")
        track_id = find_or_add_track(cur, artist_id, track_parts["title"])
        collaborator_count = add_collaborators(cur, video_id, artist_id, track_parts["featured"])
    else:
        release_id = find_or_add_release(cur, artist_id, extraction["title"], extraction["kind"])

    cur.execute(
        "INSERT INTO reviews (video_id, artist_id, release_id, track_id, score_text, summary, quote, quote_start_s) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (video_id, artist_id, release_id, track_id, extraction["score_text"], extraction["summary"],
         pull_quote.get("quote"), pull_quote.get("start_s")),
    )

    # a track review he liked is itself a recommendation, backed by the pull quote
    if track_id is not None and extraction["liked"]:
        take = {
            "summary": extraction["summary"],
            "quote": pull_quote.get("quote"),
            "start_s": pull_quote.get("start_s"),
        }
        add_endorsement(cur, video_id, track_id, "track_review", take)
        endorsement_count += 1

    # every fav track from the description, with his spoken take on it when there is one
    takes_by_fav_track = {}
    for take in extraction["track_takes"]:
        if take["fav_track"] and take["fav_track"] not in takes_by_fav_track:
            takes_by_fav_track[take["fav_track"]] = take

    endorsed_track_ids = set()
    for fav_track in extraction["fav_tracks"]:
        fav_track_id = find_or_add_track(cur, artist_id, fav_track)
        # "RED LIGHTS" and "REDLIGHTS" listed twice would be the same track, so only endorse it once
        if fav_track_id in endorsed_track_ids:
            continue
        endorsed_track_ids.add(fav_track_id)
        add_endorsement(cur, video_id, fav_track_id, "fav_track", takes_by_fav_track.get(fav_track))
        endorsement_count += 1

    from_artist_ids = {connection["about_artist"]: artist_id for connection in extraction["connections"]}
    connection_count, dropped_names = add_spoken_connections(
        cur, video_id, extraction["connections"], from_artist_ids, matcher
    )

    summary = (f"{endorsement_count} songs, {connection_count + collaborator_count} connections, "
               f"{len(dropped_names)} names dropped")
    return summary, dropped_names


def load_roundup(cur, video_id: str, extraction: dict, matcher: NameMatcher) -> tuple[str, list[dict]]:
    """writes a weekly track roundup: every best track is a song he recommends, every "ft."
    credit is a collaborator, and every spoken comparison is a connection from that track's
    artist. returns (a short summary for the progress line, the dropped names)."""
    endorsement_count = 0
    collaborator_count = 0
    artist_ids = {}
    endorsed_track_ids = set()

    for track in extraction["tracks"]:
        artist_id = find_or_add_artist(cur, track["artist"])
        artist_ids[track["artist"]] = artist_id
        collaborator_count += add_collaborators(cur, video_id, artist_id, track["featured"])

        # meh and worst tracks still give us collaborators above, but they aren't recommendations
        if track["verdict"] != "best":
            continue
        track_id = find_or_add_track(cur, artist_id, track["title"])
        if track_id in endorsed_track_ids:
            continue
        endorsed_track_ids.add(track_id)
        add_endorsement(cur, video_id, track_id, "best_track", track["take"])
        endorsement_count += 1

    # about_artist was set by extract.py from the track list, so it's always in artist_ids
    connection_count, dropped_names = add_spoken_connections(
        cur, video_id, extraction["connections"], artist_ids, matcher
    )

    summary = (f"{endorsement_count} songs, {connection_count + collaborator_count} connections, "
               f"{len(dropped_names)} names dropped")
    return summary, dropped_names


# --- files and statuses ---

def save_dropped_names(video_id: str, dropped_names: list[dict]) -> None:
    """writes this video's dropped names to data/logs/dropped_names/{id}.json. overwritten
    every run, so reloading a video never piles up duplicates."""
    dropped_file = DROPPED_NAMES_DIR / f"{video_id}.json"
    dropped_file.write_text(json.dumps(dropped_names, ensure_ascii=False, indent=2))


def save_status(conn, video_id: str, status: str) -> None:
    """sets load_status to "done" or "failed" and commits. for "done" this is the same commit
    as the video's rows, so a video is never marked loaded with half its rows missing."""
    with conn.cursor() as cur:
        cur.execute("UPDATE videos SET load_status = %s WHERE id = %s", (status, video_id))
    conn.commit()


# --- running the stage ---

def parse_args() -> argparse.Namespace:
    """reads the command line flags: nothing (load what's pending), --video ID, or --reload."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    which_videos = parser.add_mutually_exclusive_group()
    which_videos.add_argument("--video", help="reload one video id")
    which_videos.add_argument("--reload", action="store_true", help="reload every extracted video")
    return parser.parse_args()


def fetch_videos(conn, args: argparse.Namespace) -> list[dict]:
    """the videos to load this run, based on the flags."""
    with conn.cursor() as cur:
        if args.video:
            cur.execute(SINGLE_VIDEO_SQL, (args.video,))
        elif args.reload:
            cur.execute(ALL_EXTRACTED_VIDEOS_SQL)
        else:
            cur.execute(PENDING_VIDEOS_SQL)
        return cur.fetchall()


def fetch_reviewed_names(conn) -> list[str]:
    """rule 1's list: the artist of every review title on the channel."""
    with conn.cursor() as cur:
        cur.execute(REVIEWED_ARTISTS_SQL)
        return [row["subject_artist"] for row in cur.fetchall()]


def main() -> None:
    args = parse_args()
    user_agent = build_user_agent()
    MUSICBRAINZ_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DROPPED_NAMES_DIR.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        matcher = NameMatcher(fetch_reviewed_names(conn), user_agent)
        videos = fetch_videos(conn, args)
        print(f"{len(videos)} videos to load")

        for position, video in enumerate(videos, start=1):
            progress = f"[{position}/{len(videos)}] {video['id']}"
            extraction = json.loads(video["extraction"])

            try:
                with conn.cursor() as cur:
                    delete_video_rows(cur, video["id"])
                    if video["type"] == "roundup":
                        summary, dropped_names = load_roundup(cur, video["id"], extraction, matcher)
                    else:
                        summary, dropped_names = load_review(cur, video["id"], extraction, matcher)
            except httpx.HTTPError as error:
                # musicbrainz is down or blocking us. stop and leave the rest pending
                conn.rollback()
                print(f"{progress} STOPPED  musicbrainz: {error}")
                print("nothing is lost: rerun later and it picks up from here.")
                sys.exit(1)
            except Exception as error:
                # something about this one video broke a constraint or the data shape. throw away
                # its half-written rows, mark it failed, and keep going with the next one
                conn.rollback()
                print(f"{progress} FAILED   {type(error).__name__}: {error}")
                save_status(conn, video["id"], "failed")
                continue

            save_dropped_names(video["id"], dropped_names)
            save_status(conn, video["id"], "done")
            print(f"{progress} ok  {summary}  {video['title']}")


if __name__ == "__main__":
    main()
