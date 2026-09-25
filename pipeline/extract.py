"""Stage 3: turn each captioned video into facts, using the AI only for what he says out loud.

Reads:  videos rows + data/captions/{id}.json
Writes: data/raw_llm/{id}.json (the AI's answer, before any checks)

Step A of the build: this version only calls the AI and saves its raw answer.
Verification and saving to videos.extraction come next.
"""

import argparse
import json
import sys
from pathlib import Path

from db import connect
from description import parse_review
from llm import LLMUnavailable, generate_json

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CAPTIONS_DIR = DATA_DIR / "captions"
RAW_DIR = DATA_DIR / "raw_llm"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

LABELS = ["sounds_like", "influenced_by", "contrast", "collaborator"]

# The exact shape Gemini must return for album and track reviews (see prompts/review.md).
# The API enforces it: field names, types, and the 4 allowed labels.
QUOTE_FIELDS = {"line": {"type": "integer"}, "quote": {"type": "string"}}
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
        "connections": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "artist": {"type": "string"},
                "heard_as": {"type": "string"},
                "about_artist": {"type": "string"},
                "label": {"type": "string", "enum": LABELS},
                **QUOTE_FIELDS,
            },
            "required": ["artist", "heard_as", "about_artist", "label", "line", "quote"],
        }},
        "track_takes": {"type": "array", "items": {
            "type": "object",
            "properties": {"track": {"type": "string"}, "summary": {"type": "string"}, **QUOTE_FIELDS},
            "required": ["track", "line", "quote", "summary"],
        }},
    },
    "required": ["liked", "summary", "pull_quote", "connections", "track_takes"],
}

# Same shape as captions.py: take the newest N in-scope videos first, then keep the
# ones still pending. Roundups are added in step C.
PENDING_SQL = """
SELECT id, title, type, description, subject_artist, subject_title FROM (
  SELECT * FROM videos
  WHERE type IN ('album_review', 'track_review')
  ORDER BY published_at DESC
  LIMIT %s
) AS newest
WHERE captions_status = 'done' AND extract_status = 'pending'
ORDER BY published_at DESC
"""
ONE_VIDEO_SQL = "SELECT id, title, type, description, subject_artist, subject_title FROM videos WHERE id = %s"


# --- Pure functions: building the AI's input ---

def fmt_time(seconds: float) -> str:
    """190.2 -> "3:10" """
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def format_transcript(lines: list[dict]) -> str:
    """Caption-file lines -> the text the AI reads: one "[44 @ 3:10] words" per line."""
    return "\n".join(f"[{ln['line']} @ {fmt_time(ln['start'])}] {ln['text']}" for ln in lines)


def build_review_input(video: dict, lines: list[dict]) -> str:
    """Title + his fav tracks (read from the description by code) + the numbered transcript.
    Giving the AI the fav tracks means it doesn't have to guess which songs matter."""
    fav = parse_review(video["description"] or "")["fav_tracks"]
    fav_line = f"FAV TRACKS: {', '.join(fav)}\n" if fav else ""
    return f"TITLE: {video['title']}\n{fav_line}TRANSCRIPT:\n{format_transcript(lines)}"


# --- Reading and writing files ---

def load_lines(video_id: str) -> list[dict]:
    """The numbered caption lines saved by captions.py (stage 2)."""
    return json.loads((CAPTIONS_DIR / f"{video_id}.json").read_text())


def get_ai_answer(video: dict, lines: list[dict], refresh: bool) -> dict:
    """The AI's answer for this video. Reuses data/raw_llm/{id}.json if it exists, so
    rerunning the later steps costs no Gemini quota. --refresh asks the AI again."""
    path = RAW_DIR / f"{video['id']}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    answer = generate_json(
        prompt=(PROMPTS_DIR / "review.md").read_text(),
        text=build_review_input(video, lines),
        schema=REVIEW_SCHEMA,
    )
    path.write_text(json.dumps(answer, ensure_ascii=False, indent=2))
    return answer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--limit", type=int, help="the newest N reviews")
    group.add_argument("--video", help="one video ID")
    parser.add_argument("--refresh", action="store_true", help="ask the AI again even if an answer is saved")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn, conn.cursor() as cur:
        if args.video:
            cur.execute(ONE_VIDEO_SQL, (args.video,))
        else:
            cur.execute(PENDING_SQL, (args.limit,))
        videos = cur.fetchall()
    print(f"{len(videos)} videos to extract")

    for i, video in enumerate(videos, 1):
        tag = f"[{i}/{len(videos)}] {video['id']}"
        try:
            answer = get_ai_answer(video, load_lines(video["id"]), args.refresh)
        except LLMUnavailable as e:
            print(f"{tag} STOPPED  {e}\nNothing is lost: rerun later and it resumes from here.")
            sys.exit(1)
        except ValueError as e:                       # unusable answer for this one video
            print(f"{tag} FAILED   {e}")
            continue
        print(f"{tag} ok  {len(answer['connections'])} connections, "
              f"{len(answer['track_takes'])} track takes  {video['title']}")


if __name__ == "__main__":
    main()
