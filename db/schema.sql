-- Fantano database schema (MySQL 8.4)
-- The pipeline writes rows that must fit these tables and web app's SQL queries reads them
--
-- Runs automatically on the first "docker compose up" (empty volume only)

-- One row per YouTube upload
CREATE TABLE videos (
  id              VARCHAR(11)  PRIMARY KEY,              -- YouTube video ID (always 11 characters)
  title           VARCHAR(255) NOT NULL,
  description     TEXT,
  published_at    DATETIME     NOT NULL,
  duration_s      INT,
  type            ENUM('album_review', 'track_review', 'roundup', 'other') NOT NULL,        -- ENUM: column can only hold one of these exact string values (rejects anything else)
  subject_artist  VARCHAR(255),               -- best-effort parse of the title
  subject_title   VARCHAR(255),
  captions_status ENUM('pending', 'done', 'failed') NOT NULL DEFAULT 'pending',             -- how pipeline tracks progress per video
  extract_status  ENUM('pending', 'done', 'failed') NOT NULL DEFAULT 'pending',
  load_status     ENUM('pending', 'done', 'failed') NOT NULL DEFAULT 'pending',
  extraction      JSON,                      -- verified AI output (stage 3)
  
  INDEX idx_videos_type_date (type, published_at)          -- speeds up query by indexing via ultizing B Trees for this column (drawback: costs additional disk space)
                                                           -- (i.e newest N videos w/ type = album_reviews)
);


-- One row per artist
CREATE TABLE artists (
  id          INT AUTO_INCREMENT PRIMARY KEY,              -- AUTO_INCREMENT; mysql assigns next number automatically
  name        VARCHAR(255) NOT NULL,                       -- display name
  name_key    VARCHAR(255) NOT NULL,                       -- "A$AP Rocky" -> "asaprocky"
  mbid        CHAR(36) UNIQUE,                             -- MusicBrainz ID; NULLs allowed, duplicates not
  image_url   VARCHAR(512),
  is_reviewed BOOLEAN NOT NULL DEFAULT FALSE,              -- has >= 1 review -> shows up in search

  INDEX idx_artists_name_key (name_key)               -- index artists via name_key quickly and often
);

-- albums, each belonging to an artist
CREATE TABLE releases (
  id        INT AUTO_INCREMENT PRIMARY KEY,
  artist_id INT NOT NULL,
  title     VARCHAR(255) NOT NULL,
  title_key VARCHAR(255) NOT NULL,                         -- same normalization as artists.name_key
  kind      ENUM('album', 'ep', 'mixtape') NOT NULL,
  cover_url VARCHAR(512),

  UNIQUE (artist_id, title_key),                  -- composite unique constraint (two columns in each record must be unique; one record can have a same column but not both)
  FOREIGN KEY (artist_id) REFERENCES artists (id) -- foreign key operation to associate both tables based off artist_id (artist_id must match a real row in artists table)
);

-- songs, each belonging to an artist (similar structure to releases)
CREATE TABLE tracks (
  id        INT AUTO_INCREMENT PRIMARY KEY,
  artist_id INT NOT NULL,
  title     VARCHAR(255) NOT NULL,
  title_key VARCHAR(255) NOT NULL,
  cover_url VARCHAR(512),

  UNIQUE (artist_id, title_key),
  FOREIGN KEY (artist_id) REFERENCES artists (id)
);


-- One row per album and track review video
CREATE TABLE reviews (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  video_id      VARCHAR(11) NOT NULL UNIQUE,               -- one review per video
  artist_id     INT NOT NULL,
  release_id    INT,                                       -- set for album reviews
  track_id      INT,                                       -- set for track reviews
  score_text    VARCHAR(32),                               -- "7/10", shown as-is
  summary       TEXT,                                      -- AI summary, never shown in quotes
  quote         TEXT,                                      -- his real words
  quote_start_s INT,

  FOREIGN KEY (video_id)   REFERENCES videos (id),        -- 4 foreign key operations to associate table to other tables based off primary key (form connections requiring ids to match across tables)
  FOREIGN KEY (artist_id)  REFERENCES artists (id),
  FOREIGN KEY (release_id) REFERENCES releases (id),
  FOREIGN KEY (track_id)   REFERENCES tracks (id),
  CHECK ((release_id IS NULL) <> (track_id IS NULL))       -- exactly one of the release_id/track_id must be NULL and other must not be 
                                                           -- (i.e a review is either about an album or a track but never both)
);


-- "Fantano linked A to B in video V at second S."
CREATE TABLE connections (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  video_id       VARCHAR(11) NOT NULL,                     -- proof is required
  from_artist_id INT NOT NULL,                             -- who was being discussed
  to_artist_id   INT NOT NULL,                             -- who he brought up
  label          ENUM('sounds_like', 'influenced_by', 'contrast', 'collaborator') NOT NULL,
  quote          TEXT,
  start_s        INT,

  FOREIGN KEY (video_id)       REFERENCES videos (id),
  FOREIGN KEY (from_artist_id) REFERENCES artists (id),
  FOREIGN KEY (to_artist_id)   REFERENCES artists (id),
  CHECK (label = 'collaborator' OR start_s IS NOT NULL),   -- spoken links need a timestamp
  CHECK (from_artist_id <> to_artist_id)                   -- no "SZA sounds like SZA"
);


-- Songs Fantano recommends (i.e X Tracks Fantano Recommends section on web app)
CREATE TABLE endorsements (
  id       INT AUTO_INCREMENT PRIMARY KEY,
  track_id INT NOT NULL,
  video_id VARCHAR(11) NOT NULL,
  source   ENUM('fav_track', 'best_track', 'track_review') NOT NULL,
  summary  TEXT,
  quote    TEXT,
  start_s  INT,                                            -- NULL when he never discussed it aloud

  UNIQUE (track_id, video_id),                             -- one endorsement per track per video
  FOREIGN KEY (track_id) REFERENCES tracks (id),
  FOREIGN KEY (video_id) REFERENCES videos (id)
);
