"""stage 3: extract. turns each captioned video into facts we can trust, and saves them for stage 4.

for every review or roundup that has captions, this script:
  1. reads what code can read on its own: the artist and album from the title (collect.py
     already parsed it) and the score, fav tracks, or track lists from the description
     (description.py)
  2. asks Gemini (through llm.py) for the stuff that only exists in his speech: a summary,
     the artists he compares things to, and his quotes, each tied to a transcript line number
  3. checks every ai item against the captions. a quote has to actually be there, near the
     line the ai cited, or it gets dropped. timestamps always come from the caption file
  4. saves the merged result to videos.extraction and logs whatever got dropped

usage:
    uv run extract.py --limit 50                     # the newest 50 reviews and roundups
    uv run extract.py --video Zt2esoyoTgs            # just one video, handy for testing
    uv run extract.py --video Zt2esoyoTgs --refresh  # ignore the saved ai answer and ask again

reads:   videos rows (MySQL) and data/captions/{id}.json (from captions.py)
writes:  data/raw_llm/{id}.json        the ai's answer before any checks. reused on reruns,
                                       so re-checking a video costs no Gemini quota
         videos.extraction             the verified facts. this is what load.py (stage 4) reads
         data/logs/dropped/{id}.json   every ai item that failed a check, and why
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

from rapidfuzz import fuzz

from db import connect
from description import parse_review, parse_roundup
from llm import LLMUnavailable, generate_json

# where everything lives on disk
PIPELINE_DIR = Path(__file__).resolve().parent
DATA_DIR = PIPELINE_DIR.parent / "data"
CAPTIONS_DIR = DATA_DIR / "captions"
RAW_AI_DIR = DATA_DIR / "raw_llm"
DROPPED_DIR = DATA_DIR / "logs" / "dropped"
PROMPTS_DIR = PIPELINE_DIR / "prompts"

# the only 4 ways he can relate two artists
CONNECTION_LABELS = ["sounds_like", "influenced_by", "contrast", "collaborator"]

# how similar two strings have to be (0-100) to count as the same words.
# 85 lets caption typos and a dropped "uh" through, but not a paraphrase
FUZZY_MATCH_THRESHOLD = 85

# a bit stricter, for "is this 'other' artist actually the one being reviewed?"
SAME_ARTIST_THRESHOLD = 90

# how many lines on each side of the cited line we search.
# the name has to be close because the timestamp comes from that line.
# quotes often start a few lines before the name, so they get more room
NAME_SEARCH_LINES = 2
QUOTE_SEARCH_LINES = 6


# --- the answer shapes Gemini has to follow ---
# llm.py sends these along and the api enforces them, so every answer has exactly these
# fields with these types, and a label can only ever be one of the 4 above

REVIEW_CONNECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "artist": {"type": "string"},
        "heard_as": {"type": "string"},
        "about_artist": {"type": "string"},
        "label": {"type": "string", "enum": CONNECTION_LABELS},
        "line": {"type": "integer"},
        "quote": {"type": "string"},
    },
    "required": ["artist", "heard_as", "about_artist", "label", "line", "quote"],
}

REVIEW_TRACK_TAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "track": {"type": "string"},
        "line": {"type": "integer"},
        "quote": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": ["track", "line", "quote", "summary"],
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "liked": {"type": "boolean"},
        "summary": {"type": "string"},
        "pull_quote": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "line": {"type": "integer"}},
            "required": ["text", "line"],
        },
        "connections": {"type": "array", "items": REVIEW_CONNECTION_SCHEMA},
        "track_takes": {"type": "array", "items": REVIEW_TRACK_TAKE_SCHEMA},
    },
    "required": ["liked", "summary", "pull_quote", "connections", "track_takes"],
}

# in roundups the ai points at tracks by their number in the list we send it (1, 2, 3...),
# never by name, so it can't misspell them. code fills in the names afterwards

ROUNDUP_TRACK_TAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "track": {"type": "integer"},
        "line": {"type": "integer"},
        "quote": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": ["track", "line", "quote", "summary"],
}

ROUNDUP_CONNECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "track": {"type": "integer"},
        "artist": {"type": "string"},
        "heard_as": {"type": "string"},
        "label": {"type": "string", "enum": CONNECTION_LABELS},
        "line": {"type": "integer"},
        "quote": {"type": "string"},
    },
    "required": ["track", "artist", "heard_as", "label", "line", "quote"],
}

ROUNDUP_SCHEMA = {
    "type": "object",
    "properties": {
        "track_takes": {"type": "array", "items": ROUNDUP_TRACK_TAKE_SCHEMA},
        "connections": {"type": "array", "items": ROUNDUP_CONNECTION_SCHEMA},
    },
    "required": ["track_takes", "connections"],
}


# --- picking which videos to work on ---

# same idea as captions.py: grab the newest N reviews and roundups first, then keep the ones
# that have captions and haven't been extracted yet. that way --limit 50 always means
# "the newest 50", no matter how many times you rerun it
PENDING_VIDEOS_SQL = """
SELECT id, title, type, description, subject_artist, subject_title FROM (
  SELECT * FROM videos
  WHERE type <> 'other'
  ORDER BY published_at DESC
  LIMIT %s
) AS newest
WHERE captions_status = 'done' AND extract_status = 'pending'
ORDER BY published_at DESC
"""

# --video skips the status filter on purpose, so you can redo one video while testing
SINGLE_VIDEO_SQL = """
SELECT id, title, type, description, subject_artist, subject_title FROM videos WHERE id = %s
"""


# --- building what the ai reads ---

def format_timestamp(seconds: float) -> str:
    """turns seconds into m:ss, e.g. 190.2 -> "3:10"."""
    minutes, seconds_left = divmod(int(seconds), 60)
    return f"{minutes}:{seconds_left:02d}"


def format_transcript(caption_lines: list[dict]) -> str:
    """turns the caption file into the text the ai reads, one line per caption line:

        [44 @ 3:10] which honestly gives me some frank ocean

    the number up front is what the ai cites back to us, so it never has to come up with
    a timestamp itself.
    """
    formatted_lines = []
    for caption in caption_lines:
        timestamp = format_timestamp(caption["start"])
        formatted_lines.append(f"[{caption['line']} @ {timestamp}] {caption['text']}")
    return "\n".join(formatted_lines)


def build_review_ai_input(video: dict, caption_lines: list[dict]) -> str:
    """builds everything the ai reads for an album or track review: the video title, his fav
    tracks (read from the description by code), and the numbered transcript.

    handing over the fav tracks means the ai doesn't have to guess which songs matter.
    without them it skipped most of his favorites.
    """
    fav_tracks = parse_review(video["description"] or "")["fav_tracks"]

    parts = [f"TITLE: {video['title']}"]
    if fav_tracks:
        parts.append(f"FAV TRACKS: {', '.join(fav_tracks)}")
    parts.append("TRANSCRIPT:")
    parts.append(format_transcript(caption_lines))
    return "\n".join(parts)


def format_roundup_track(number: int, track: dict) -> str:
    """one entry of the numbered roundup track list the ai reads, e.g.
    "10. [best] Joy Crookes - Painkiller (ft. Denzel Curry)"."""
    entry = f"{number}. [{track['verdict']}] {track['artist']} - {track['title']}"
    if track["featured"]:
        entry += f" (ft. {', '.join(track['featured'])})"
    return entry


def build_roundup_ai_input(video: dict, roundup_tracks: list[dict], caption_lines: list[dict]) -> str:
    """builds everything the ai reads for a weekly track roundup: the title, the numbered
    track list from the description, and the numbered transcript. the ai refers back to
    tracks by those numbers."""
    track_list = [
        format_roundup_track(number, track)
        for number, track in enumerate(roundup_tracks, start=1)
    ]
    return "\n".join([
        f"TITLE: {video['title']}",
        "TRACKS:",
        *track_list,
        "TRANSCRIPT:",
        format_transcript(caption_lines),
    ])


# --- comparing the ai's words with the captions ---

def normalize_text(text: str) -> str:
    """squashes text down to plain lowercase words, so we compare what was said and not how
    it's typed. accents, punctuation, and extra spaces all go away:

        "Beyoncé's, uh... FORMATION" -> "beyonces uh formation"
    """
    # "é" -> "e": split accented letters into letter + accent, then drop the accent
    without_accents = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()

    # drop apostrophes first so "don't" turns into "dont" and not "don t"
    lowercase = without_accents.lower().replace("'", "")

    letters_and_digits = re.sub(r"[^a-z0-9 ]", " ", lowercase)
    return " ".join(letters_and_digits.split())


def to_title_key(title: str) -> str:
    """like normalize_text, but also drops the spaces, since song titles get spaced
    differently all the time: "Red Lights" and "REDLIGHTS" both become "redlights"."""
    return normalize_text(title).replace(" ", "")


def line_exists(caption_lines: list[dict], line_number: int) -> bool:
    """did the ai cite a line that's actually in the transcript?"""
    return 0 <= line_number < len(caption_lines)


def get_nearby_text(caption_lines: list[dict], line_number: int, lines_around: int) -> str:
    """the caption text from `lines_around` lines before `line_number` to `lines_around`
    lines after it, glued into one string. this is the "near the cited line" zone."""
    first_line = max(0, line_number - lines_around)
    last_line = line_number + lines_around
    return " ".join(caption["text"] for caption in caption_lines[first_line:last_line + 1])


def is_said_near_line(text: str, caption_lines: list[dict], line_number: int, lines_around: int) -> bool:
    """is `text` (a name or a quote) in the captions near `line_number`?

    uses rapidfuzz's partial_ratio: it slides `text` along the nearby captions, scores the
    best spot from 0 to 100, and 85 or up counts as "he said it there".
    """
    nearby_text = get_nearby_text(caption_lines, line_number, lines_around)
    score = fuzz.partial_ratio(normalize_text(text), normalize_text(nearby_text))
    return score >= FUZZY_MATCH_THRESHOLD


def split_artist_names(artist: str) -> list[str]:
    """the full artist credit plus each person in it, so a duo counts as itself and as both
    of its members:

        "Erykah Badu & The Alchemist" -> ["Erykah Badu & The Alchemist", "Erykah Badu", "The Alchemist"]
    """
    members = re.split(r"\s+(?:&|and|x)\s+|,\s*", artist, flags=re.IGNORECASE)
    return [artist] + [member for member in members if member and member != artist]


def is_same_artist(name: str, own_artist_names: list[str]) -> bool:
    """is `name` one of the artists already credited on this release or track? those aren't
    connections, it's just the artist being compared to themself."""
    for own_name in own_artist_names:
        if fuzz.ratio(normalize_text(name), normalize_text(own_name)) >= SAME_ARTIST_THRESHOLD:
            return True
    return False


# --- checking the ai's answer ---
# each check returns the reason an item gets dropped, or None if it's fine

def find_quote_problem(quote: str, line_number: int, caption_lines: list[dict]) -> str | None:
    """checks one quote the ai gave us: the cited line has to exist, and the quote has to
    show up within 6 lines of it. used for pull quotes, track takes, and connections.

    returns why the quote should be dropped, or None if it passes.
    """
    if not line_exists(caption_lines, line_number):
        return f"line {line_number} doesn't exist"
    if not quote.strip():
        return "quote is empty"
    if not is_said_near_line(quote, caption_lines, line_number, QUOTE_SEARCH_LINES):
        return f"quote not found near line {line_number}"
    return None


def find_connection_problem(connection: dict, caption_lines: list[dict], own_artist_names: list[str]) -> str | None:
    """checks one artist connection the ai gave us. it passes if all of these hold, in order:

      1. the cited line exists
      2. the other artist's name is said within 2 lines of it. either spelling counts:
         heard_as (the caption's spelling) or artist (the proper one), because the ai once
         garbled heard_as for a caption that clearly says "Björk"
      3. the quote shows up within 6 lines of it
      4. the label is one of the 4
      5. the other artist isn't the one being discussed (no "SZA sounds like SZA")

    returns why the connection should be dropped, or None if it passes.
    """
    line_number = connection["line"]
    if not line_exists(caption_lines, line_number):
        return f"line {line_number} doesn't exist"

    name_was_said = False
    for spelling in (connection["heard_as"], connection["artist"]):
        if spelling and is_said_near_line(spelling, caption_lines, line_number, NAME_SEARCH_LINES):
            name_was_said = True
    if not name_was_said:
        return f"name {connection['heard_as']!r} not spoken near line {line_number}"

    quote_problem = find_quote_problem(connection["quote"], line_number, caption_lines)
    if quote_problem:
        return quote_problem

    if connection["label"] not in CONNECTION_LABELS:
        return f"unknown label {connection['label']!r}"

    if is_same_artist(connection["artist"], own_artist_names):
        return f"{connection['artist']!r} is the artist being discussed (self-link)"

    return None


def find_matching_fav_track(track_title: str, fav_tracks: list[str]) -> str | None:
    """which of his fav tracks (as written in the description) a track take is about, or
    None if it isn't one of them. titles are compared loosely because spellings drift:
    "Red Lights" matches "REDLIGHTS", and the caption typo "Witchd Doctor" matches
    "WITCH DOCTOR"."""
    best_match = None
    best_score = 0
    for fav_track in fav_tracks:
        score = fuzz.ratio(to_title_key(track_title), to_title_key(fav_track))
        if score > best_score:
            best_match, best_score = fav_track, score

    if best_score >= FUZZY_MATCH_THRESHOLD:
        return best_match
    return None


def parse_release_kind(title: str) -> str | None:
    """what kind of release a review is about, read from the video title:
    "Mk.gee - Two Star EP REVIEW" -> "ep". it's one of album, ep, mixtape, or track."""
    match = re.search(r"\b(ALBUM|EP|MIXTAPE|TRACK) REVIEWS?\b", title, re.IGNORECASE)
    if match:
        return match[1].lower()
    return None


def add_timestamp(item: dict, caption_lines: list[dict]) -> dict:
    """returns a copy of `item` with start_s (seconds into the video) looked up from its
    line in the caption file. this is the only place timestamps come from, the ai never
    gives us one."""
    start_seconds = int(caption_lines[item["line"]]["start"])
    return {**item, "start_s": start_seconds}


# --- merging everything into videos.extraction ---

def build_review_extraction(video: dict, ai_answer: dict, caption_lines: list[dict]) -> tuple[dict, list[dict]]:
    """merges everything we know about one album or track review into the dict that gets
    saved to videos.extraction:

      - from the title (collect.py): kind, artist, title
      - from the description (description.py): score_text, fav_tracks, least_fav
      - from the ai, only the parts that passed the checks: liked, summary, pull_quote,
        connections, track_takes (each quote with its line and start_s)

    returns (extraction, dropped_items). dropped_items lists what failed a check and why.
    """
    description_facts = parse_review(video["description"] or "")
    own_artist_names = split_artist_names(video["subject_artist"])
    dropped_items = []

    # the ai calls the pull quote's words "text", rename it to "quote" to match every other quote
    pull_quote = {"quote": ai_answer["pull_quote"]["text"], "line": ai_answer["pull_quote"]["line"]}
    problem = find_quote_problem(pull_quote["quote"], pull_quote["line"], caption_lines)
    if problem:
        dropped_items.append({"kind": "pull_quote", "reason": problem, "item": pull_quote})
        verified_pull_quote = None
    else:
        verified_pull_quote = add_timestamp(pull_quote, caption_lines)

    verified_connections = []
    for connection in ai_answer["connections"]:
        problem = find_connection_problem(connection, caption_lines, own_artist_names)
        if problem:
            dropped_items.append({"kind": "connection", "reason": problem, "item": connection})
            continue
        verified_connections.append(add_timestamp(connection, caption_lines))

    verified_track_takes = []
    for track_take in ai_answer["track_takes"]:
        problem = find_quote_problem(track_take["quote"], track_take["line"], caption_lines)
        if problem:
            dropped_items.append({"kind": "track_take", "reason": problem, "item": track_take})
            continue
        # note which fav track this is, so stage 4 can put his quote on that recommended song
        fav_track = find_matching_fav_track(track_take["track"], description_facts["fav_tracks"])
        verified_track_takes.append(add_timestamp({**track_take, "fav_track": fav_track}, caption_lines))

    extraction = {
        "kind": parse_release_kind(video["title"]),
        "artist": video["subject_artist"],
        "title": video["subject_title"],
        "score_text": description_facts["score_text"],
        "fav_tracks": description_facts["fav_tracks"],
        "least_fav": description_facts["least_fav"],
        "liked": ai_answer["liked"],
        "summary": ai_answer["summary"],
        "pull_quote": verified_pull_quote,
        "connections": verified_connections,
        "track_takes": verified_track_takes,
    }
    return extraction, dropped_items


def build_roundup_extraction(video: dict, ai_answer: dict, caption_lines: list[dict]) -> tuple[dict, list[dict]]:
    """merges everything we know about one weekly track roundup into the dict that gets
    saved to videos.extraction:

      - tracks: every track from the description's best / meh / worst lists (artist, title,
        featured, verdict), each with "take" = his verified quote and summary, or None if
        he never talked about it
      - connections: the verified artist connections. about_artist is filled in by code
        from the track list, not by the ai

    returns (extraction, dropped_items). dropped_items lists what failed a check and why.
    """
    roundup_tracks = parse_roundup(video["description"] or "")["tracks"]
    track_count = len(roundup_tracks)
    dropped_items = []

    # his take on each track, keyed by the track's number in the list (starting at 1)
    takes_by_track_number = {}
    for track_take in ai_answer["track_takes"]:
        track_number = track_take["track"]
        if not 1 <= track_number <= track_count:
            problem = f"track #{track_number} isn't in the list"
        else:
            problem = find_quote_problem(track_take["quote"], track_take["line"], caption_lines)
        if problem:
            dropped_items.append({"kind": "track_take", "reason": problem, "item": track_take})
            continue

        # if the ai gave two takes for the same track, the first one wins
        if track_number in takes_by_track_number:
            continue
        take = {"quote": track_take["quote"], "summary": track_take["summary"], "line": track_take["line"]}
        takes_by_track_number[track_number] = add_timestamp(take, caption_lines)

    verified_connections = []
    for connection in ai_answer["connections"]:
        track_number = connection["track"]
        if not 1 <= track_number <= track_count:
            problem = f"track #{track_number} isn't in the list"
            dropped_items.append({"kind": "connection", "reason": problem, "item": connection})
            continue

        track = roundup_tracks[track_number - 1]
        # in a roundup, "self" means the track's own artist or anyone featured on it
        own_artist_names = split_artist_names(track["artist"]) + track["featured"]
        problem = find_connection_problem(connection, caption_lines, own_artist_names)
        if problem:
            dropped_items.append({"kind": "connection", "reason": problem, "item": connection})
            continue

        connection_with_artist = {**connection, "about_artist": track["artist"]}
        verified_connections.append(add_timestamp(connection_with_artist, caption_lines))

    tracks_with_takes = []
    for track_number, track in enumerate(roundup_tracks, start=1):
        tracks_with_takes.append({**track, "take": takes_by_track_number.get(track_number)})

    extraction = {"tracks": tracks_with_takes, "connections": verified_connections}
    return extraction, dropped_items


# --- files and the database ---

def load_caption_lines(video_id: str) -> list[dict]:
    """reads the numbered caption lines that captions.py (stage 2) saved for this video."""
    caption_file = CAPTIONS_DIR / f"{video_id}.json"
    return json.loads(caption_file.read_text())


def ask_ai(video: dict, caption_lines: list[dict]) -> dict:
    """sends one video to Gemini (through llm.py) with the right prompt and answer shape for
    its type, and returns the answer as a dict."""
    if video["type"] == "roundup":
        roundup_tracks = parse_roundup(video["description"] or "")["tracks"]
        prompt_file = "roundup.md"
        ai_input = build_roundup_ai_input(video, roundup_tracks, caption_lines)
        answer_schema = ROUNDUP_SCHEMA
    else:
        prompt_file = "review.md"
        ai_input = build_review_ai_input(video, caption_lines)
        answer_schema = REVIEW_SCHEMA

    prompt = (PROMPTS_DIR / prompt_file).read_text()
    return generate_json(prompt=prompt, text=ai_input, schema=answer_schema)


def get_ai_answer(video: dict, caption_lines: list[dict], refresh: bool) -> dict:
    """the ai's answer for this video. if we already asked before, the saved answer in
    data/raw_llm/{id}.json gets reused, so rerunning the checks costs no Gemini quota.
    refresh=True (the --refresh flag) ignores it and asks again, e.g. after a prompt change."""
    saved_answer_file = RAW_AI_DIR / f"{video['id']}.json"
    if saved_answer_file.exists() and not refresh:
        return json.loads(saved_answer_file.read_text())

    answer = ask_ai(video, caption_lines)
    # ensure_ascii=False keeps "Björk" readable in the file instead of "Björk"
    saved_answer_file.write_text(json.dumps(answer, ensure_ascii=False, indent=2))
    return answer


def save_dropped_items(video_id: str, dropped_items: list[dict]) -> None:
    """writes what got dropped for this video to data/logs/dropped/{id}.json. one file per
    video, overwritten every run, so rerunning a video never piles up duplicate entries."""
    dropped_file = DROPPED_DIR / f"{video_id}.json"
    dropped_file.write_text(json.dumps(dropped_items, ensure_ascii=False, indent=2))


def save_result(conn, video_id: str, status: str, extraction: dict | None = None) -> None:
    """saves this video's extract_status ("done" or "failed") and its extraction, then commits
    right away so progress is kept one video at a time, same as captions.py."""
    extraction_json = json.dumps(extraction, ensure_ascii=False) if extraction is not None else None
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE videos SET extract_status = %s, extraction = %s WHERE id = %s",
            (status, extraction_json, video_id),
        )
    conn.commit()


# --- running the stage ---

def parse_args() -> argparse.Namespace:
    """reads the command line flags: --limit N or --video ID (you need exactly one), plus
    an optional --refresh."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    which_videos = parser.add_mutually_exclusive_group(required=True)
    which_videos.add_argument("--limit", type=int, help="the newest N reviews and roundups")
    which_videos.add_argument("--video", help="one video id")
    parser.add_argument("--refresh", action="store_true", help="ask the ai again even if an answer is saved")
    return parser.parse_args()


def fetch_videos(conn, args: argparse.Namespace) -> list[dict]:
    """the videos to work on this run: just the one for --video, or the newest pending ones
    for --limit."""
    with conn.cursor() as cur:
        if args.video:
            cur.execute(SINGLE_VIDEO_SQL, (args.video,))
        else:
            cur.execute(PENDING_VIDEOS_SQL, (args.limit,))
        return cur.fetchall()


def find_missing_input(video: dict) -> str | None:
    """the ai is only worth calling once code has read what the checks depend on: a parsed
    title for reviews, and track lists in the description for roundups. the ai never fills
    these in. returns what's missing, or None if the video is good to go."""
    if video["type"] == "roundup":
        if not parse_roundup(video["description"] or "")["tracks"]:
            return "description has no track lists"
    elif not video["subject_artist"]:
        return "title didn't parse"
    return None


def main() -> None:
    args = parse_args()
    RAW_AI_DIR.mkdir(parents=True, exist_ok=True)
    DROPPED_DIR.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        videos = fetch_videos(conn, args)
        print(f"{len(videos)} videos to extract")

        for position, video in enumerate(videos, start=1):
            progress = f"[{position}/{len(videos)}] {video['id']}"

            # nothing solid to check the ai against, so don't spend a request on it
            missing = find_missing_input(video)
            if missing:
                print(f"{progress} FAILED   {missing}: {video['title']}")
                save_dropped_items(video["id"], [{"kind": "video", "reason": missing}])
                save_result(conn, video["id"], "failed")
                continue

            caption_lines = load_caption_lines(video["id"])
            try:
                ai_answer = get_ai_answer(video, caption_lines, args.refresh)
            except LLMUnavailable as error:
                # rate limit or daily quota. stop here and leave the rest pending for next time
                print(f"{progress} STOPPED  {error}")
                print("nothing is lost: rerun later and it picks up from here.")
                sys.exit(1)
            except ValueError as error:
                # the answer for this one video was unusable (cut off or blocked), so move on
                print(f"{progress} FAILED   {error}")
                save_result(conn, video["id"], "failed")
                continue

            if video["type"] == "roundup":
                extraction, dropped_items = build_roundup_extraction(video, ai_answer, caption_lines)
                take_count = sum(1 for track in extraction["tracks"] if track["take"] is not None)
            else:
                extraction, dropped_items = build_review_extraction(video, ai_answer, caption_lines)
                take_count = len(extraction["track_takes"])

            save_dropped_items(video["id"], dropped_items)
            save_result(conn, video["id"], "done", extraction)
            print(f"{progress} ok  kept {len(extraction['connections'])} connections, "
                  f"{take_count} takes; dropped {len(dropped_items)}  {video['title']}")


if __name__ == "__main__":
    main()
