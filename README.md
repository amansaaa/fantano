# Fantano

Search for an artist Anthony Fantano (theneedledrop) has reviewed and see which artists he connected them to, plus the songs he recommends from those artists. Every connection and recommendation links to the exact timestamp in the video where he said it.

## Background

- Anthony Fantano is a music reviewer with thousands of review videos over the years.
- Often during these videos he makes comparisons between artists. Those connections only exist inside each video, so you'd be required to watch tons of videos to find new artists you might like.
- Fantano turns all of that into a searchable database that links to the exact moment he connected two artists, so you can search for your favourite artist and find new ones.

## How it works

- Scrapes 5000+ of Fantano's YouTube music reviews into a searchable database of artists.
- A batch data pipeline pulls video metadata and transcripts.
- Plain code (regex) reads the artist, the album, his score, his favorite tracks, and the weekly best/meh/worst lists which stays consistent across most of his videos (title and description)
- LLM is used only for what requires understanding speech: which artists he compared (each comparison gets one of 4 labels), his quotes, and AI generated summaries of Fantano's opinion.
- Deterministic code then verifies every AI quote against the source transcript, so every fact in the app links to the exact second Fantano said it.

## Quick start

> Work in progress 

**Requirements:** Docker, Python with uv, Node.js, YouTube Data API key, Gemini API key.

```bash
# 1. Config: fill in your keys in .env
cp .env.example .env
ln -s ../.env web/.env.local

# 2. Start MySQL
docker compose up -d

# 3. Run the pipeline, one stage at a time
cd pipeline
uv run collect.py
uv run captions.py --limit 50
uv run extract.py
uv run load.py
uv run images.py

# 4. Start the web app
cd ../web
npm install
npm run dev
```

Then open http://localhost:3000.

## Architecture

### Overview

```
 OFFLINE                                           ONLINE (runs for each page view)
 ┌──────────────────────────────────────────┐      ┌──────────────────────────────┐
 │  Pipeline (Python)                       │      │  Web app (Next.js)           │
 │  YouTube → captions → AI → clean data    │ ───► │  reads the database only     │
 │  slow, rate-limited, uses API keys       │MySQL │  fast, needs no API keys     │
 └──────────────────────────────────────────┘      └──────────────────────────────┘
        "write path"                                       "read path"
```

Getting captions and running the AI on one video takes seconds to minutes, and both YouTube and the free AI tier are rate-limited. If that happened while someone was using the site, they'd wait a long time. So all the expensive work happens ahead of time, and the web app only runs `SELECT` queries.

Follows the standard pattern: ETL (Extract, Transform, Load) / batch processing feeding a read only frontend.

### Pipeline

```
collect → captions → extract + verify → match names + load → images
```

**Rules:**

1. **Stages only talk through saved data** (MySQL or `data/`). If a stage fails, we only rerun that stage instead of the whole pipeline. That saves a lot of LLM calls and means we don't redownload metadata and captions.
2. **Every video tracks its progress** (`pending` / `done` / `failed` per stage). If YouTube blocks us or we hit the AI's daily limit, we can pick up where we left off. Each stage is idempotent, and we can scale to more videos by raising `--limit` and rerunning.
3. **Captions and raw AI responses are saved**, so we can iterate on our prompts without scraping again.

#### Stage 1: Collect (`collect.py`)

- Asks the YouTube Data API for the channel's uploads and stores one row per video.
- Classifies each video by title only (no AI) and parses the artist and album from it (`SZA - SOS ALBUM REVIEW` → `SZA`, `SOS`). This works for all but ~20 of 3,600+ reviews, including older titles written `Artist- Title`. The rest are skipped and logged.
- Stores metadata for every video (5,000+), since it costs almost no quota.

| id | title | type | subject_artist | subject_title |
|---|---|---|---|---|
| abc123XYZ00 | SZA - SOS ALBUM REVIEW | album_review | SZA | SOS |
| def456... | Weekly Track Roundup: 12/18 | roundup | — | — |
| ghi789... | I'm moving to a new studio | other | — | — |

#### Stage 2: Captions (`captions.py`)

- Downloads YouTube's auto-generated subtitles for the newest N reviews and roundups, and saves them to a file with numbered lines.
- Waits 10 seconds between videos. If YouTube blocks requests, it stops and leaves the rest `pending`; rerunning resumes where it left off.

```json
// data/captions/abc123XYZ00.json
[{"line": 44, "start": 190.2, "text": "which honestly gives me some frank ocean"},
 {"line": 45, "start": 192.8, "text": "blonde vibes on this track"}]
```

#### Stage 3: Extract + verify (`extract.py` + `description.py` + `llm.py`)

Each video is read by two readers, and their results are saved together as one JSON per video.

**1. `description.py` reads the description (plain code, no AI).** Fantano writes these facts in a fixed format, so regex reads them exactly:

```
FAV TRACKS: DIFFERENT RELIGION, REDLIGHTS        !!!BEST TRACKS THIS WEEK!!!
LEAST FAV TRACK: ORBIT                           Joy Crookes - Painkiller ft. Denzel Curry
5/10                                             ...meh...
                                                 Troye Sivan - Party
```

```json
{"score_text": "5/10", "fav_tracks": ["DIFFERENT RELIGION", "REDLIGHTS"]}
{"artist": "Joy Crookes", "title": "Painkiller", "featured": ["Denzel Curry"], "verdict": "best"}
```

Measured on the newest 1,000 videos: 97% of reviews have a score, 93% have fav tracks, and 100% of roundups have track lists. When a pattern doesn't match, the field is left empty, never guessed.

**2. The AI reads the transcript.** `extract.py` formats the captions as numbered lines and sends them to Gemini with the instructions in `prompts/review.md`:

```
[44 @ 3:10] which honestly gives me some frank ocean
[45 @ 3:12] blonde vibes on this track
```

It returns structured JSON:

```json
{"summary": "He finds the album too long but praises the vocals and a few standout tracks.",
 "pull_quote": {"text": "this is sza at her most confident", "line": 312},
 "connections": [{"artist": "Frank Ocean", "heard_as": "frank ocean", "about_artist": "SZA",
   "label": "sounds_like", "line": 44, "quote": "gives me some frank ocean blonde vibes"}],
 "track_takes": [{"track": "Kill Bill", "line": 188, "quote": "kill bill is easily the best song here",
   "summary": "He calls it the standout track."}]}
```

- Labels describe how he related two artists: `sounds_like`, `influenced_by`, `contrast`, `collaborator`. The similar artists grid shows all four; the recommended tracks list leaves out `contrast`.
- `summary` is the AI's own words and is never shown in quotation marks. Everything in quotation marks is his real words.
- `track_takes` give the recommended songs (fav tracks from the description) his quote and a timestamp.
- `llm.py` is the only file that talks to the AI: `generate_json(prompt, text, schema)` sends an HTTP request to Gemini and returns a dict. The API enforces the JSON schema. Rate limits are retried with exponential backoff (10s, 20s, 40s); if Gemini stays unavailable, the run stops and resumes later. Switching AI providers means rewriting only this file.

**3. Plain code checks everything the AI said:**
- The AI cites line numbers instead of timestamps, because LLMs are bad at precise numbers (they predict text; they don't do arithmetic like a calculator). The code looks up the real timestamp from the line.
- Does line 44 exist?
- Does "frank ocean" appear near line 44 (fuzzy match ≥ 85)?
- Does the quote match the real words around line 44?
- Is `sounds_like` one of the 4 allowed labels?
- Fuzzy string matching (the `rapidfuzz` library) scores from 0 to 100 how many characters you'd need to change to turn the AI's quote into the real transcript. It never tries to understand what the words mean.
- Anything that fails a check is dropped and logged.

#### Stage 4: Match names + load (`load.py`)

- Turns every artist name into an ID, since the `connections` table only holds artist IDs (`from_artist_id`, `to_artist_id`).
- Checks each name against the artists Fantano has reviewed, and otherwise against MusicBrainz, to confirm the string is actually a real artist.
- Spelling variants collapse into one artist (`A$AP Rocky` and `ASAP Rocky` are the same row). Names that can't be matched confidently are dropped and logged.

```
artists
  1  SZA          (is_reviewed = true)
  2  Frank Ocean
  7  A$AP Rocky   (already existed)

connections
  video        from  to  label         quote   start_s
  abc123XYZ00  1     2   sounds_like   "..."   190
  abc123XYZ00  1     7   contrast      "..."   455
```

#### Stage 5: Images (`images.py`)

- Asks Deezer for artist photos and album covers, and only stores the URLs (free to use; nothing to store or host).

### Database

**Why a database instead of JSON files?** With JSON files we'd need to load everything into memory and write the core logic ourselves: grouping artists by connection, counting distinct videos, picking timestamps, etc. With a database that's a single query. A database also enforces foreign keys and uniqueness, and a `CHECK` constraint makes sure every spoken connection has a timestamp.

**Relational vs. non-relational:** it comes down to the shape of the data.

- **Relational:** Frank Ocean is one row and everything else points to his ID. If we update his photo, every page that shows him updates too.
- **Non-relational (document DB):** Frank Ocean would be copied into every document that mentions him, so there are many copies to keep in sync, and finding everything linked to him means scanning every document.
- **Graph database:** connections are a graph, but every query only goes one hop (just Frank Ocean's neighbours) and the dataset is small. SQL handles one hop easily.

Our data is heavily cross-referenced (relationships between artists, labels, videos and timestamps of each mention), which is exactly what relational databases are built for.

## Tech stack

### `pipeline/`: data pipeline

- **Python w/ uv**
- **YouTube Data API v3**
- **youtube-transcript-api**
- **httpx**
- **Gemini 3.5 Flash-Lite**
- **rapidfuzz**: fuzzy string matching
- **MusicBrainz**: open music database 
- **Deezer API**: artist photo and album cover images

### `db/` + `docker-compose.yml`: database

- **MySQL 8.4**
- **Docker Compose**

### `web/`: web app

- **Next.js + TypeScript**: server components query MySQL directly (no separate backend to build)
- **mysql2 with plain SQL (no ORM)**: server side has only read queries so ORM isn't necessary
- **Tailwind CSS**
