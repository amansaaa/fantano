# Fantano

Search for an artist Anthony Fantano (theneedledrop) has reviewed and see which artists he connected them to, plus the songs he recommends from those artists. Every connection and recommendation links to the exact timestamp in the video where he said it.

## Background

- Anthony Fantano is a music reviewer with thousands of review videos over the years.
- Often during these videos he makes comparisons between artists. Those connections only exist inside each video, so you'd be required to watch tons of videos to find new artists you might like.
- Fantano turns all of that into a searchable database that links to the exact moment he connected two artists, so you can search for your favourite artist and find new ones.

For example, when you search "SZA", her page shows her reviews, the artists Fantano connected her to, and songs by those artists that he recommended. Every item has a `▶ Watch @ 3:12` link that opens YouTube at the exact second he says it.

## How it works

- Scrapes ~200 of theneedledrop's YouTube music reviews into a searchable database of artists.
- A batch data pipeline pulls transcripts and uses an LLM to extract which artists he compared to each other (each comparison gets one of 4 labels) and which songs he liked.
- It then verifies every extraction against the source transcript with deterministic code, so every fact in the app links to the exact second Fantano said it.

## Quick start

> Work in progress 

**Requirements:** Docker, Python with [uv](https://docs.astral.sh/uv/), Node.js, a YouTube Data API key, and a Gemini API key.

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
 OFFLINE (runs on your Mac, when you choose)         ONLINE (runs for each page view)
 ┌──────────────────────────────────────────┐      ┌──────────────────────────────┐
 │  Pipeline (Python)                       │      │  Web app (Next.js)           │
 │  YouTube → captions → AI → clean data    │ ───► │  reads the database only     │
 │  slow, rate-limited, uses API keys       │MySQL │  fast, needs no API keys     │
 └──────────────────────────────────────────┘      └──────────────────────────────┘
        "write path"                                       "read path"
```

**Why split it this way?** Getting captions and running the AI on one video takes seconds to minutes, and both YouTube and the free AI tier are rate-limited. If that happened while someone was using the site, they'd wait a long time. So all the expensive work happens ahead of time, and the web app only runs `SELECT` queries.

This is a standard pattern: ETL / batch processing (Extract, Transform, Load) feeding a read-only frontend.

### Database

**Why a database instead of JSON files?** With JSON files we'd need to load everything into memory and write the core logic ourselves: grouping artists by connection, counting distinct videos, picking timestamps, etc. With a database that's a single query. A database also enforces foreign keys and uniqueness, and a `CHECK` constraint makes sure every spoken connection has a timestamp.

**Relational vs. non-relational:** it comes down to the shape of the data.

- **Relational:** Frank Ocean is one row and everything else points to his ID. If we update his photo, every page that shows him updates too.
- **Non-relational (document DB):** Frank Ocean would be copied into every document that mentions him, so there are many copies to keep in sync, and finding everything linked to him means scanning every document.
- **Graph database:** connections are a graph, but every query only goes one hop (just Frank Ocean's neighbours) and the dataset is small. SQL handles one hop easily.

Our data is heavily cross-referenced (relationships between artists, labels, videos and timestamps of each mention), which is exactly what relational databases are built for.

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
- Classifies each video by title only (no AI; cheap and good enough).
- Stores metadata for every video, since it costs almost no quota.

| id | title | type | subject_artist | subject_title |
|---|---|---|---|---|
| abc123XYZ00 | SZA - SOS ALBUM REVIEW | album_review | SZA | SOS |
| def456... | Weekly Track Roundup: 12/18 | roundup | — | — |
| ghi789... | I'm moving to a new studio | other | — | — |

#### Stage 2: Captions (`captions.py`)

- Downloads YouTube's auto-generated subtitles and saves them to a file.

```json
// data/captions/abc123XYZ00.json
[{"line": 44, "start": 190.2, "text": "which honestly gives me some frank ocean"},
 {"line": 45, "start": 192.8, "text": "blonde vibes on this track"}]
```

#### Stage 3: Extract + verify (`extract.py` + `llm.py`)

- The AI reads the transcript, with numbered lines:

```
[44 @ 3:10] which honestly gives me some frank ocean
[45 @ 3:12] blonde vibes on this track
```

- It returns structured JSON:

```json
{"connections": [{"artist": "Frank Ocean", "heard_as": "frank ocean",
  "label": "sounds_like", "line": 44, "quote": "gives me some frank ocean blonde vibes"}]}
```

Labels describe how he related two artists: `sounds_like`, `influenced_by`, `contrast`, `collaborator`.
- The similar artists grid shows all four labels.
- The recommended tracks list leaves out `contrast`.

- The AI cites line numbers instead of timestamps, because LLMs are bad at precise numbers (they predict text; they don't do arithmetic like a calculator). The code looks up the real timestamp from the line.
- Plain code then checks everything the AI said:
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

## Tech stack

### `pipeline/`: data pipeline

- **Python w/ uv**: python libraries needed for captions, fuzzy matching, API clients
- **YouTube Data API v3**: video metadata
- **Gemini Flash API**: JSON output mode (switch providers requires just changing `llm.py`)
- **rapidfuzz**: fuzzy string matching for verifying names and quotes after LLM stage
- **MusicBrainz**: open music database with a permanent ID for every artist
- **Deezer API**: artist photos and album covers

### `db/` + `docker-compose.yml`: database

- **MySQL 8.4**: relational data with constraints
- **Docker Compose**: containerize MySQL DB

### `web/`: web app

- **Next.js + TypeScript**: server components query MySQL directly (no separate backend to build)
- **mysql2 with plain SQL (no ORM)**: server side has only read queries so ORM isn't necessary
- **Tailwind CSS**: styling
