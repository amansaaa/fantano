# Fantano

> Search an artist Anthony Fantano (theneedledrop) reviewed → see which artists he connected them to and the songs he recommends from those artists, each backed by a timestamped link to the exact moment he said it.

This file is the project's design doc, and it's loaded into every Claude session. **When a decision changes, update this file.**

## Working in this repo
- **Stages talk only through saved data** (MySQL + `data/`). Never pass data between stages in memory.
- **`pipeline/llm.py` is the only file that knows the AI provider.**
- **`db/schema.sql` is the source of truth for tables.** Section 5 below is a sketch of it.
- **The web app uses plain SQL through `mysql2` (no ORM).**
- **Keep the page rules in section 6 exactly as written.** They're meant to be simple enough to explain in an interview, so don't add rules without asking.

---

## 1. Goals

**MVP (1–2 days, runs locally):**
- Scrape a small batch of theneedledrop's newest videos ourselves (start with **50**, grow to **~200**).
- Turn them into a clean database of artists, connections, and recommended songs — every item with proof.
- A local web app: search → artist page, styled after the reference screenshots.

**Priority:** understand the architecture end to end > squeeze out accuracy. Every stage can be upgraded later without touching the others.

**Not in the MVP:** song pages, deployment, manual data review, more than ~200 videos, and video types other than the three below.

---

## 2. Key decisions

| Decision | Why |
|---|---|
| Only **album/EP/mixtape reviews**, **single-track reviews**, and **Weekly Track Roundups** | Clear structure. Roundups are the main source of recommended songs. |
| Transcripts = **YouTube auto-captions** | Minutes instead of days; accuracy is good enough. |
| **One AI request per video** (two prompts: review, roundup) | Simple, cheap, transcript sent once. |
| **Code verifies every AI quote and timestamp** against the transcript | Proof must be real — AI output is never trusted blindly. |
| **MusicBrainz ID** is an artist's identity (`UNIQUE` in the DB) | Prevents "ASAP Rocky" + "A$AP Rocky" duplicates. |
| **Automatic name matching**; unsure → drop + log | No manual review time; never publish a bad guess. |
| **MySQL 8.4** | The data is relational: one artist/song row, referenced from many places, with constraints that keep it clean. Chosen over Postgres to diversify. |
| **Deezer** for artist photos and covers (store URLs only) | Free, no API key, fast. |
| **Free Gemini tier** behind one file (`llm.py`); Mistral free tier as fallback | Free. Switching providers is a one-file change. |
| **Four connection labels:** Sounds like · Influenced by · Contrast · Collaborator | Few, clearly different labels → consistent AI labeling. Non-musical name-drops are ignored. |
| **Grid shows all connections** (good and bad); **track list only has songs he liked** | The grid is what he said; the track list is what he'd actually recommend. |
| **Quotation marks = Fantano's real words + a timestamp.** AI summaries are never in quotes. | Keeps the "proof" honest. |

---

## 3. Architecture

```
                       pipeline/  (Python, runs on your Mac)
  ┌──────────┐   ┌───────────┐   ┌─────────────────┐   ┌──────────────┐   ┌──────────┐
  │1 collect │ → │2 captions │ → │3 extract+verify │ → │4 match+load  │ → │5 images  │
  │ YouTube  │   │ auto-subs │   │  AI + checks    │   │ names → IDs  │   │ Deezer   │
  └────┬─────┘   └─────┬─────┘   └────────┬────────┘   └──────┬───────┘   └────┬─────┘
       │               │                  │                   │                │
       ▼               ▼                  ▼                   ▼                ▼
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │ MySQL: videos · artists · releases · tracks · reviews · connections · endorsements│
  └──────────────────────────────────────┬───────────────────────────────────────────┘
       data/ (gitignored): captions/, raw_llm/, logs/
                                         │
                                         ▼
                               web/  (Next.js) → browser
```

**Three rules make this easy to reason about and to upgrade:**

1. **Stages only talk through saved data.** Each stage reads what the previous one saved (MySQL or `data/`) and writes its own output. Nothing is passed in memory, so you can run, debug, or replace one stage at a time.
2. **Every video tracks its progress.** `videos` has a status per stage (`pending` / `done` / `failed`). Each script only processes videos not yet `done`. Rerunning is safe; adding more videos = raise `--limit` and rerun.
3. **Raw inputs are kept forever.** Captions and raw AI responses are saved, so later stages (e.g., after a prompt tweak) can be rerun without re-scraping.

---

## 4. Pipeline stages

### Stage 1 — Collect (`pipeline/collect.py`)
- **In:** the channel handle `@theneedledrop`.
- **Out:** one `videos` row per upload (title, description, date, duration, type, subject from title).
- **How:** YouTube Data API v3 with a free API key from Google Cloud.
  `channels.list?forHandle=@theneedledrop` → uploads playlist → `playlistItems.list` (50 per page) → `videos.list` for full descriptions and durations. Pulling metadata for every video uses only a few hundred of the free 10,000 daily quota units.
- **Classify by title** (case-insensitive):
  - `ALBUM REVIEW` / `EP REVIEW` / `MIXTAPE REVIEW` → `album_review`
  - `TRACK REVIEW` → `track_review`
  - `Weekly Track Roundup` → `roundup`
  - anything else → `other` (ignored)
- **Subject from the title** (`Artist - Title TYPE`), best effort (~90%). When the pattern doesn't match, the AI fills in the subject in stage 3.
- Store metadata for all videos (it's cheap). Later stages only process the **N newest** non-`other` videos.
- The artists named in **all** review titles form the **reviewed-artist list** used by name matching (stage 4).

### Stage 2 — Captions (`pipeline/captions.py`)
- **In:** videos whose `captions_status` is `pending` (newest N, in scope).
- **Out:** `data/captions/{video_id}.json`
  ```json
  [{"line": 0, "start": 0.0, "text": "hi everyone fantano here"}, ...]
  ```
- **How:** the `youtube-transcript-api` Python package. Wait a few seconds between videos and run from home Wi-Fi. If YouTube blocks requests, stop and resume later; status tracking makes that safe. Fallback: `yt-dlp --write-auto-subs --skip-download`.

### Stage 3 — Extract + verify (`pipeline/extract.py`, `pipeline/llm.py`)
- **In:** a video row plus its captions.
- **Out:** the raw AI response in `data/raw_llm/{video_id}.json`, and the **verified** result in `videos.extraction` (a JSON column). Dropped items go to `data/logs/dropped_items.jsonl`.
- **`llm.py`** exposes one function, `extract(video) -> dict`, and is the only file that knows which AI provider is used. It uses the provider's JSON/structured-output mode.
- **Prompt input** — numbered transcript lines so the AI cites *line numbers*, never timestamps it made up:
  ```
  TITLE: SZA - SOS ALBUM REVIEW
  DESCRIPTION: ...
  TRANSCRIPT:
  [0 @ 0:00] hi everyone fantano here the internet's busiest music nerd
  [1 @ 0:04] ...
  ```
- **Review prompt output** (album and track reviews):
  ```json
  {
    "subject": {"artist": "SZA", "title": "SOS", "kind": "album"},
    "score_text": "7/10",
    "liked": true,
    "summary": "2–3 sentence AI summary of his verdict",
    "pull_quote": {"text": "his actual words", "line": 312},
    "fav_tracks": ["Kill Bill", "Ghost in the Machine"],
    "connections": [
      {"artist": "Frank Ocean", "heard_as": "frank ocean", "about_artist": "SZA",
       "label": "sounds_like", "line": 45, "quote": "his actual words"}
    ],
    "track_takes": [
      {"track": "Kill Bill", "line": 188, "quote": "his actual words", "summary": "1–2 sentences"}
    ]
  }
  ```
  `liked` only matters for track reviews: a liked track review counts as an endorsement.
- **Roundup prompt output:**
  ```json
  {
    "tracks": [
      {"artist": "Doja Cat", "title": "Tension", "featured": [], "verdict": "best",
       "line": 210, "quote": "his actual words", "summary": "1–2 sentences"}
    ],
    "connections": [ ...same shape as above; about_artist = the track's artist... ]
  }
  ```
  `verdict` is `best` / `meh` / `worst`, taken from the description's `!!!BEST TRACKS THIS WEEK!!!` / `...meh...` / `!!!WORST TRACKS THIS WEEK!!!` lists.
- **Verification (plain code, no AI).** Any item that fails a check is dropped and logged:
  1. The cited `line` exists in the transcript.
  2. `heard_as` fuzzy-matches (≥ 85) the text of lines `line-2 … line+2`. This proves the name was spoken there; correcting the name is stage 4's job.
  3. `quote` fuzzy-matches (≥ 85) lines `line-2 … line+3`. That allows light cleanup of filler words and caption typos, but not invented words.
  4. Every `fav_tracks` entry and every roundup track appears in the description.
  5. `label` is one of the four allowed labels.
- **Timestamp links:** `https://www.youtube.com/watch?v={id}&t={max(0, start-5)}s`. Starting 5 seconds early lets the viewer hear the lead-in.

### Stage 4 — Match names + load (`pipeline/load.py`)
- **In:** `videos.extraction` (names are still plain strings).
- **Out:** rows in `artists`, `releases`, `tracks`, `reviews`, `connections`, `endorsements`. Unmatched names go to `data/logs/dropped_names.csv`.
- **Name → artist** (the whole rule):
  > Keep a name only if **(1)** it matches an artist Fantano reviewed, or **(2)** it matches exactly one MusicBrainz artist almost perfectly. Otherwise drop it.
  1. Fuzzy match (`rapidfuzz`, ≥ 90) against the reviewed-artist list from stage 1.
  2. Otherwise, MusicBrainz artist search: accept only if the top score is ≥ 95 **and** at least 10 points ahead of #2, and use MusicBrainz's official name. MusicBrainz allows 1 request per second and requires a User-Agent that includes a contact email.
  3. Otherwise, drop and log.
- **No duplicates:** look up by `mbid` first, then by `name_key`, and insert only if both miss. `name_key` = lowercase, accents stripped, `$`→`s`, punctuation removed, so `A$AP Rocky` and `ASAP Rocky` both become `asaprocky`.
- **Collaborators:** artists after `feat.` / `ft.` in roundup track names and track-review titles become `collaborator` connections, from the track's credits rather than from speech. After the MVP: MusicBrainz credits.
- `connections.from_artist_id` = the artist being discussed when he made the link: the album's artist in reviews, the track's artist in roundups.

### Stage 5 — Images (`pipeline/images.py`)
- **Artist photos:** Deezer `search/artist?q={name}` → `picture_xl`, accepted only if the result's name is a close match (≥ 90).
- **Album covers:** Deezer `search/album?q=artist:"{artist}" album:"{title}"` → `cover_xl`.
- **Track covers:** Deezer `search/track?q=artist:"{artist}" track:"{title}"` → the album's cover.
- Only URLs are stored; no images are downloaded. If nothing matches, the UI shows a gray silhouette or blank square. Stay under Deezer's rate limit (roughly 50 requests per 5 seconds).

---

## 5. Database (MySQL 8.4, `utf8mb4`)

```sql
videos (
  id              VARCHAR(11) PRIMARY KEY,               -- YouTube video ID
  title           VARCHAR(255),
  description     TEXT,
  published_at    DATETIME,
  duration_s      INT,
  type            ENUM('album_review','track_review','roundup','other'),
  captions_status ENUM('pending','done','failed') DEFAULT 'pending',
  extract_status  ENUM('pending','done','failed') DEFAULT 'pending',
  load_status     ENUM('pending','done','failed') DEFAULT 'pending',
  extraction      JSON NULL                              -- verified AI output (stage 3)
);

artists (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  name        VARCHAR(255),
  name_key    VARCHAR(255), INDEX (name_key),            -- "asaprocky"
  mbid        CHAR(36) NULL UNIQUE,                      -- MusicBrainz ID: the no-duplicates rule
  image_url   VARCHAR(512) NULL,
  is_reviewed BOOLEAN DEFAULT FALSE                      -- has ≥1 review → searchable
);

releases (
  id        INT AUTO_INCREMENT PRIMARY KEY,
  artist_id INT NOT NULL REFERENCES artists(id),
  title     VARCHAR(255),
  kind      ENUM('album','ep','mixtape'),
  cover_url VARCHAR(512) NULL
);

tracks (
  id        INT AUTO_INCREMENT PRIMARY KEY,
  artist_id INT NOT NULL REFERENCES artists(id),
  title     VARCHAR(255),
  title_key VARCHAR(255),
  cover_url VARCHAR(512) NULL,
  UNIQUE (artist_id, title_key)
);

reviews (                                                -- album + track reviews (not roundups)
  id            INT AUTO_INCREMENT PRIMARY KEY,
  video_id      VARCHAR(11) NOT NULL UNIQUE REFERENCES videos(id),
  artist_id     INT NOT NULL REFERENCES artists(id),
  release_id    INT NULL REFERENCES releases(id),        -- album reviews
  track_id      INT NULL REFERENCES tracks(id),          -- track reviews
  score_text    VARCHAR(32) NULL,                        -- e.g. "7/10", shown as-is
  summary       TEXT,                                    -- AI summary (never in quotes)
  quote         TEXT NULL,                               -- his real words
  quote_start_s INT NULL
);

connections (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  video_id       VARCHAR(11) NOT NULL REFERENCES videos(id),   -- proof is required
  from_artist_id INT NOT NULL REFERENCES artists(id),
  to_artist_id   INT NOT NULL REFERENCES artists(id),
  label          ENUM('sounds_like','influenced_by','contrast','collaborator'),
  quote          TEXT NULL,
  start_s        INT NULL,
  CHECK (label = 'collaborator' OR start_s IS NOT NULL)        -- spoken links need a timestamp
);

endorsements (                                           -- "songs he liked"
  id       INT AUTO_INCREMENT PRIMARY KEY,
  track_id INT NOT NULL REFERENCES tracks(id),
  video_id VARCHAR(11) NOT NULL REFERENCES videos(id),
  source   ENUM('fav_track','best_track','track_review'),
  summary  TEXT NULL,
  quote    TEXT NULL,
  start_s  INT NULL,                                     -- NULL when he never discusses the track aloud
  UNIQUE (track_id, video_id)
);
```

**MySQL notes:**
- The default collation ignores case and accents ("Beyonce" = "Beyoncé"). That's good for search, and it's why the no-duplicates rule sits on `mbid` instead of `name`.
- A `UNIQUE` column allows many `NULL`s, so artists without a MusicBrainz ID still fit.
- `CHECK` constraints are enforced in MySQL 8.0.16+.
- In the real `schema.sql`, write foreign keys at the table level: `FOREIGN KEY (artist_id) REFERENCES artists(id)`. MySQL 8.4 silently ignores inline `REFERENCES` on a column (the shorthand in the sketch above).
- `videos` also stores `subject_artist` and `subject_title`, the best-effort parse of the title from stage 1.

---

## 6. Web app (`web/` — Next.js + TypeScript + Tailwind)

Server components query MySQL directly with `mysql2` and **plain SQL** (no ORM), so every query is visible.

### Pages
- **`/` Home**
  - **Layout:** a centered cartoon logo, the headline "Discover music from the internet's busiest music nerd," a pill-shaped search box, and album covers floating around it (covers of recently reviewed releases).
  - **Search:** typing calls `GET /api/search?q=`, which runs
    `SELECT id, name FROM artists WHERE is_reviewed AND name LIKE CONCAT('%', ?, '%') LIMIT 8`.
    MySQL's collation handles case and accents for free. Results appear in an **ARTISTS** dropdown.
- **`/artist/[id]` Artist page:** described below. Artists who were only mentioned use the same page with no review box, plus an "Every time Fantano mentioned X" list with timestamps. They're reachable from cards but don't appear in search.

### Artist page

**Left column**
- Artist photo (gray silhouette if missing) and name.
- **Review box with ‹ › arrows:**
  - It cycles through this artist's reviews, newest first, with a position indicator ("2 / 6").
  - Each review shows the release title, score, and AI summary (no quotation marks).
  - Below that: one real quote in quotation marks with **▶ Watch @ m:ss**.

**"Similar artists according to Fantano" grid**
- Includes every connection where this artist is the `from` **or** the `to` artist, so both directions count.
- Groups by the other artist and ranks by **number of different videos** linking them. Ties go to the most recent video.
- The label under each photo is the pair's **most frequent** label.
- Shows the top 12, plus a **"Show all N"** button.

**"N Tracks Fantano recommends"**
> Pick songs **round-robin** across the similar artists (in grid order, skipping cards labeled Contrast) until there are **12**, then **show each artist's songs together**.
- "Songs" = that artist's tracks with an endorsement (`fav_track`, `best_track`, or a liked `track_review`), newest first.
- The heading shows the real count ("6 Tracks…" if only 6 qualify).
- Each row shows:
  - cover, title, and artist
  - the AI summary (no quotation marks)
  - **why it's recommended:** his real quote plus **▶ Watch @ time**. If he never discussed the track aloud, the row says "Fav track in his *[Album]* review ▶ Watch" instead.
  - **why this artist is connected**, as a small gray line: `Fantano linked SZA → Frank Ocean · Sounds like ▶ @ 3:12` (the most recent link between the two).

### Visual style (from the reference screenshots)
- Very light, cool off-white background; near-black headings.
- Muted blue small-caps section labels.
- Pill search box with a thin dark border.
- Square photos with slightly rounded corners, and lots of whitespace.
- A geometric sans-serif font; pick the exact one when building the UI.

---

## 7. Local setup

```
fantano/
├── CLAUDE.md                    # this file
├── docker-compose.yml           # MySQL 8.4 (utf8mb4), data in a named volume
├── .env.example                 # copy to .env (gitignored); web reads it via a web/.env.local symlink
├── db/
│   └── schema.sql               # table definitions (source of truth)
├── pipeline/                    # Python, managed with uv
│   ├── pyproject.toml
│   ├── db.py                    # MySQL connection helper
│   ├── llm.py                   # extract(video) -> dict; the ONLY file that knows the AI provider
│   ├── collect.py               # stage 1
│   ├── captions.py              # stage 2
│   ├── extract.py               # stage 3 (AI + verification)
│   ├── load.py                  # stage 4 (name matching + inserts)
│   ├── images.py                # stage 5
│   └── prompts/
│       ├── review.md            # album + track reviews
│       └── roundup.md           # Weekly Track Roundups
├── data/                        # gitignored
│   ├── captions/
│   ├── raw_llm/
│   └── logs/
└── web/                         # Next.js + TypeScript + Tailwind
    └── src/
        ├── app/
        │   ├── layout.tsx
        │   ├── page.tsx             # home + search
        │   ├── globals.css
        │   ├── api/search/route.ts  # GET /api/search?q=
        │   └── artist/[id]/page.tsx # artist page
        ├── components/
        │   ├── SearchBox.tsx
        │   ├── ReviewCarousel.tsx
        │   ├── SimilarArtistsGrid.tsx
        │   └── TrackList.tsx
        └── lib/
            └── db.ts                # mysql2 connection pool
```

- **Web config files:** `package.json`, `next.config`, `tsconfig` and the other config files don't exist yet. Generate them (e.g. with `create-next-app`) when you start the web app.
- **API keys:** both Google keys (YouTube Data API and Gemini) come from the same Google account and Cloud project.

**Run order:**
```bash
docker compose up -d
cd pipeline
uv run collect.py
uv run captions.py --limit 50
uv run extract.py
uv run load.py
uv run images.py
cd ../web && npm run dev
```

---

## 8. Build order (MVP, ~2 days)

**Day 1: data**
1. MySQL in Docker, plus `db/schema.sql`.
2. `collect.py`: all metadata. Check the title classification against real titles.
3. `captions.py`: 50 videos.
4. `extract.py`: prompts plus verification. **Iterate on ~5 videos until the output looks right. This is the riskiest step.**

**Day 2: data → app**
5. `load.py`: name matching and inserts.
6. `images.py`.
7. Web: home/search and the artist page.
8. **Spot check (30 min):** open 10 artist pages and click the proof links. Does he actually say it at that moment? If yes, grow to ~200 videos by rerunning with a bigger `--limit`.

---

## 9. After the MVP (each item replaces or adds one stage)

- **More videos:** `--limit 800`, then ~3K. Free AI tiers have daily caps, so either run over several days or switch to Claude.
- **Better extraction:** Claude Sonnet 5 on Amazon Bedrock, paid with AWS Free Tier credits. Only `llm.py` changes.
- **Song pages:** reuse the artist page layout. Searchable songs = songs he discussed individually.
- **Collaborators** from MusicBrainz credits.
- **Album covers** from Cover Art Archive via MusicBrainz IDs.
- **Deploy** (below).

## 10. Deployment (later, kept simple)

- **Where:** one small EC2 or Lightsail instance running the same `docker compose` (MySQL + Next.js).
- **Data:** move it with `mysqldump`.
- **Portability:** a VPS later works exactly the same way.
- **Cost:** AWS Free plan credits cover a few months. On the Free plan the account closes when credits run out or after 6 months, so there are no surprise bills.

## 11. Risks

| Risk | Mitigation |
|---|---|
| YouTube blocks caption requests | Slow down, run from home, resume later (status tracking). |
| Free AI tier limits change | Swap the provider in `llm.py` (Mistral fallback). |
| Title/description formats differ across years | The MVP uses recent videos; the AI also reads the description as a backup. |
| Misheard names in auto-captions | Verification plus automatic matching drop them; they're logged. |
| Two different artists share a name | Rare; MusicBrainz IDs separate most cases. Acceptable for the MVP. |
