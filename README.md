# Fantano

Search for an artist Anthony Fantano (theneedledrop) has reviewed and see which artists he connected them to, plus the songs he recommends from those artists. Every connection and recommendation links to the exact moment in the video where he said it.

> **Status:** the whole pipeline is built and tested end to end. The one missing input is **transcripts**: YouTube lets one IP download captions for only ~15 videos a day, and there are ~4,000 videos to cover. So the live site runs on what Fantano **writes** in his titles and descriptions (reviews, scores, fav tracks, best tracks, "ft." credits). What he **says** (comparisons, quotes, timestamps) is the part waiting on captions. See [Design changes](#design-changes).

## Background

- Fantano has reviewed thousands of albums on YouTube, and he often compares artists while he talks ("this gives me some Frank Ocean *Blonde* vibes").
- Those connections only exist inside each video, so finding new music through them means watching hundreds of hours of video.
- This project turns them into a searchable database: search an artist you like and find the ones he connected them to, each with proof.

## How it works

- A batch **ETL pipeline** (Python) pulls every video's metadata and transcript into MySQL, and a **Next.js** app reads it.
- **Plain code reads what he writes.** Regex parses the title and description: artist, album, score, fav tracks, and the weekly best/meh/worst lists.
- **An LLM reads what he says.** It picks out which artists he compared (4 labels), his quotes, and short summaries of his opinion.
- **Code verifies everything the LLM says** against the transcript, so every quote and timestamp is real.

## Quick start

**Requirements:** Docker, Python with uv, Node.js, a YouTube Data API key, and a contact email for MusicBrainz (`MUSICBRAINZ_CONTACT`: its API requires one).

```bash
# 1. config: fill in your keys
cp .env.example .env
ln -s ../.env web/.env.local

# 2. MySQL
docker compose up -d

# 3. the pipeline, one stage at a time (what the live site runs on)
cd pipeline
uv run collect.py                      # every video's metadata
uv run extract.py --descriptions-only  # titles + descriptions, no AI
uv run load.py                         # into the tables
uv run images.py                       # photos and covers

# 4. the web app
cd ../web
npm install
npm run dev                            # http://localhost:3000
```

The spoken half runs with `uv run captions.py --limit N` and then `uv run extract.py --limit N` (needs a Gemini API key). It's paused because of the caption rate limit.

## Architecture

```
 OFFLINE                                           ONLINE (every page view)
 ┌──────────────────────────────────────────┐      ┌──────────────────────────────┐
 │  Pipeline (Python)                       │      │  Web app (Next.js)           │
 │  YouTube → captions → AI → clean data    │ ───► │  reads the database only     │
 │  slow, rate-limited, uses API keys       │MySQL │  fast, needs no API keys     │
 └──────────────────────────────────────────┘      └──────────────────────────────┘
```

All the slow, rate-limited work happens ahead of time, so a page view is only `SELECT` queries. It's the standard ETL / batch-processing pattern feeding a read-only frontend.

### Pipeline

```
collect → captions → extract + verify → match names + load → images
```

1. **Stages only talk through saved data** (MySQL or `data/`). A failed stage is rerun on its own, with no re-downloading and no repeated LLM calls.
2. **Every video tracks its progress** (`pending` / `done` / `failed` per stage). If YouTube or the LLM rate-limits a run, the next run picks up where it stopped.
3. **Raw inputs are kept** (captions, raw LLM answers), so prompts can be improved without scraping again.

#### 1. Collect: `collect.py`
- Pulls the channel's uploads from the YouTube Data API: 5,286 videos for a few hundred of the free 10,000 daily quota units.
- Classifies each video by its title: album review, track review, Weekly Track Roundup, or other (ignored).
- Parses the artist and album from the title. This works for all but ~20 of 3,600+ reviews; the rest are logged, never guessed.
```
"SZA - SOS ALBUM REVIEW"  →  album_review · SZA · SOS
```

#### 2. Captions: `captions.py`
- Downloads YouTube's auto-generated captions and saves them as numbered lines.
- Stops cleanly when YouTube blocks it; the rest stay `pending` for the next run.
```json
[{"line": 44, "start": 190.2, "text": "which honestly gives me some frank ocean"}]
```

#### 3. Extract + verify: `description.py`, `extract.py`, `llm.py`
Each video is read by two readers, and the results are saved together as one JSON per video.

**What he writes → plain code (`description.py`).** The description follows a fixed format, so regex reads it exactly. On the newest 1,000 videos: 97% of reviews have a score, 93% have fav tracks, 100% of roundups have track lists. No match leaves the field empty.
```
FAV TRACKS: DIFFERENT RELIGION, REDLIGHTS     →  {"score_text": "5/10", "fav_tracks": [...]}
5/10
Joy Crookes - Painkiller ft. Denzel Curry     →  {"artist": "Joy Crookes", "featured": ["Denzel Curry"], "verdict": "best"}
```

**What he says → the LLM (`llm.py`, Gemini).** The transcript goes in as numbered lines, and the answer comes back as JSON in a schema the API enforces:
```json
{"summary": "He finds the album too long but praises the vocals.",
 "connections": [{"artist": "Frank Ocean", "heard_as": "frank ocean", "label": "sounds_like",
                  "line": 44, "quote": "gives me some frank ocean blonde vibes"}]}
```
- 4 labels: `sounds_like`, `influenced_by`, `contrast`, `collaborator`.
- The LLM cites **line numbers**, never timestamps. Code looks up the real time, since LLMs are bad at precise numbers.
- `llm.py` is the only file that knows the provider. It retries rate limits with backoff (10s, 20s, 40s).

**Verification (plain code).** Every LLM item must pass or it's dropped and logged:
- Line 44 exists.
- "frank ocean" is really said within 2 lines of it (fuzzy match ≥ 85, `rapidfuzz`).
- The quote matches the real words nearby.
- The label is one of the 4.

#### 4. Match names + load: `load.py`
- **Written names** (titles, track lists, "ft." credits) are trusted as-is.
- **Spoken names** come from auto-captions, so each one must pass a rule: it matches an artist Fantano reviewed, or exactly one [MusicBrainz](https://musicbrainz.org) artist clearly has that name ("Jorge Ben" → Jorge Ben Jor). Otherwise it's dropped, never guessed.
- Spelling variants collapse into one artist: `A$AP Rocky` and `ASAP Rocky` share one `name_key`.
- Each video's rows are written in one transaction, and a reload replaces them, so reruns never duplicate.

#### 5. Images: `images.py`
- Artist photos and covers from Deezer. Only URLs are stored.
- Code picks the right search result: the same artist, then the closest title ("Materia", not "Materia 2").
- Coverage: 96% of artist photos, 86% of album and song covers. Misses show a gray placeholder.

### Web app

- **Home:** search his reviewed artists. MySQL's collation ignores case and accents, so "curio" finds "Curió Curió". Covers of his newest reviews float around the search box.
- **Artist page, as designed:** his reviews, the artists he connected them to, and up to 12 songs he'd recommend from those artists, each with his quote and a **▶ Watch @ 3:12** link.
- **Artist page, live today** (written data only):
  - his reviews (score and fav tracks)
  - **artists connected** through "ft." credits in his roundups
  - **songs Fantano liked by those artists** (fav tracks in their reviews, best tracks in his roundups)
- **Plain SQL at request time, never at build time**, so the build and CI need no database. The connected-artists grid is one query with CTEs and window functions. The track pick (round-robin across the grid, up to 12) is a small pure function with its own tests.

### Database

MySQL 8.4. The data is heavily cross-referenced: one artist row is pointed at by reviews, connections, and songs.

- **Relational over document DB:** Frank Ocean is one row everyone points to. A document DB would copy him into every document that mentions him, leaving many copies to keep in sync.
- **Relational over graph DB:** every query goes one hop (an artist's direct neighbours), and SQL handles that easily at this size.
- **Constraints do the policing:** foreign keys, `UNIQUE` on MusicBrainz IDs (no duplicate artists), and `CHECK` rules (no self-links; a spoken connection must have a timestamp).

### Deployment (in progress)

- **Web:** a Docker image on **Cloud Run** (scales to zero).
- **Database:** **Cloud SQL** for MySQL. The site connects as a read-only user, and its password lives in Secret Manager.
- **Pipeline:** stays local, because YouTube blocks cloud IPs even harder. `deploy/push-data.sh` copies the local database to Cloud SQL.

## Design changes

### Captions got rate-limited, so the site runs on the written half (Sep 2026)

**The constraint.** YouTube allows one IP to download captions for only ~15 videos before blocking it for about a day:

| Attempt | Pause between videos | Captions before the block |
|---|---|---|
| 1 | 3 s | 20 |
| 2 | 10 s | 12 |
| 3 | 10 s | 14 |

Slowing down didn't help: it's a daily budget per IP, not a speed limit. `yt-dlp`, even pretending to be Chrome, hit the same `429`. Cloud IPs are blocked even harder. After a week, 47 of 3,994 videos had captions.

**The reframe.** The pipeline already kept the two halves apart: code reads what he **writes**, and the LLM reads what he **says**. Only the spoken half needs captions. So every video is now loaded from its title and description (3,928 videos in 8 seconds), and the site shows only that.
- The 47 captioned videos were switched back to description-only too, so every page is built the same way.
- The page wording was changed to say what the data really is: "Artists connected to X (song credits in his roundups)" instead of "Similar artists according to Fantano".

| | Transcripts only (1 week) | Descriptions only |
|---|---|---|
| Searchable artists | 28 | 1,790 |
| Reviews | 28 | 3,587 |
| Connections | 160 | 1,938 ("ft." credits) |
| Songs he liked | 181 | 20,564 |

**What's missing.** The spoken half: "sounds like" / "influenced by" comparisons, quotes, and timestamps. The code for it is built and tested; it's waiting on captions. The reliable fix is paid rotating residential proxies (built into `youtube-transcript-api`).

**Takeaway.** When an upstream source is rate-limited, separate what depends on it from what doesn't, ship the independent part, and be honest in the product about what the data supports.

## Tech stack

- **Pipeline:** Python + uv, YouTube Data API v3, youtube-transcript-api, httpx, Gemini (Flash-Lite), rapidfuzz, MusicBrainz, Deezer.
- **Database:** MySQL 8.4, Docker Compose.
- **Web:** Next.js + TypeScript, mysql2 with plain SQL (no ORM: the site only reads), Tailwind CSS.
- **CI:** GitHub Actions: lint + tests for the pipeline and web, `schema.sql` loaded into a real MySQL, and a `next build` with no database.
- **Deploy:** Docker, Cloud Run, Cloud SQL, Secret Manager.
