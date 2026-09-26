"""stage 5: images. finds an artist photo, album cover, or song cover for every row that's missing one.

everything comes from Deezer's free search api (no key needed). we only store the image urls,
nothing gets downloaded or hosted. no match means the url stays empty, and the web app shows a
gray silhouette or a blank square instead.

a search can return anything, so code decides what counts as a match (same idea as the ai checks):
  - artist photo: a result named like the artist (>= 90) that has a real photo. if several
    share the name ("Miley Cyrus" with 7M fans and a "Miley Cyrus" with 0), the most popular wins.
    a duo credit with no photo of its own uses its first member's
  - album / song cover: a result by the same artist (or one member of a duo credit) whose title
    matches ours (>= 85). the closest title wins, so "Materia" beats "Materia 2"

deezer's field search (artist:"..." track:"...") came back empty for most songs we tried, while
a plain "Mastodon Your Ghost Again" search found them, so every search is plain text.

usage:
    uv run images.py      # every artist, release, and track that has no image yet

reads:   artists, releases, tracks rows (MySQL, from load.py)
writes:  artists.image_url, releases.cover_url, tracks.cover_url
         data/deezer/{kind}/{query_key}.json   raw deezer searches, reused on reruns
         data/logs/missing_images.json          everything that got no image this run
"""

import json
import re
import time
from pathlib import Path

import httpx
from rapidfuzz import fuzz

from db import connect
from extract import split_artist_names
from load import to_name_key

# where everything lives on disk
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEEZER_CACHE_DIR = DATA_DIR / "deezer"
MISSING_IMAGES_FILE = DATA_DIR / "logs" / "missing_images.json"

DEEZER_URL = "https://api.deezer.com"
DEEZER_RESULTS = 10
# deezer allows about 50 requests per 5 seconds, so ~8 per second leaves room to spare
DEEZER_PAUSE_SECONDS = 0.12
# deezer's "slow down" is error code 4 inside a normal 200 response, not a 429
DEEZER_QUOTA_ERROR_CODE = 4
DEEZER_MAX_ATTEMPTS = 3
DEEZER_QUOTA_WAIT_SECONDS = 5
REQUEST_TIMEOUT_SECONDS = 20

# how close names and titles have to be (0-100)
ARTIST_NAME_THRESHOLD = 90
TITLE_THRESHOLD = 85
# a long file name is fine, but keep it well under the 255 character limit
MAX_CACHE_NAME_LENGTH = 150

# "(feat. Denzel Curry)", "[Remastered]", "(Red Hot Chili Peppers Cover)"
BRACKETED_PART_PATTERN = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
# "Self-Titled (Gold)" -> the album is really called "Weezer (Gold)"
SELF_TITLED_PATTERN = re.compile(r"^self[- ]titled", re.IGNORECASE)


# --- what needs an image ---

MISSING_ARTIST_PHOTOS_SQL = "SELECT id, name FROM artists WHERE image_url IS NULL"

MISSING_RELEASE_COVERS_SQL = """
SELECT releases.id, releases.title, artists.name AS artist
FROM releases JOIN artists ON artists.id = releases.artist_id
WHERE releases.cover_url IS NULL
"""

MISSING_TRACK_COVERS_SQL = """
SELECT tracks.id, tracks.title, artists.name AS artist
FROM tracks JOIN artists ON artists.id = tracks.artist_id
WHERE tracks.cover_url IS NULL
"""


# --- asking deezer ---

def search_deezer(kind: str, query: str) -> list[dict]:
    """runs one deezer search ("artist", "album", or "track") and returns its results.

    results are saved in data/deezer/{kind}/{query_key}.json, so a rerun never asks twice.
    raises httpx.HTTPError if deezer keeps failing.
    """
    cache_name = to_name_key(query)[:MAX_CACHE_NAME_LENGTH]
    cache_file = DEEZER_CACHE_DIR / kind / f"{cache_name}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    params = {"q": query, "limit": DEEZER_RESULTS}
    for attempt in range(1, DEEZER_MAX_ATTEMPTS + 1):
        time.sleep(DEEZER_PAUSE_SECONDS)
        response = httpx.get(f"{DEEZER_URL}/search/{kind}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        body = response.json()

        error = body.get("error")
        if error and error.get("code") == DEEZER_QUOTA_ERROR_CODE and attempt < DEEZER_MAX_ATTEMPTS:
            time.sleep(DEEZER_QUOTA_WAIT_SECONDS)
            continue
        if error:
            raise httpx.HTTPError(f"deezer error: {error}")

        results = body.get("data", [])
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(results, ensure_ascii=False))
        return results

    raise httpx.HTTPError("deezer kept asking us to slow down")


# --- comparing names and titles ---

def is_real_image(url: str | None) -> bool:
    """deezer gives artists without a photo a placeholder url with an empty id in the middle:

        ".../images/artist//1000x1000-000000-80-0-0.jpg"  -> False
        ".../images/artist/59f107db.../1000x1000-...jpg"  -> True
    """
    return bool(url) and "//1000x1000" not in url


def is_same_artist(our_artist: str, deezer_artist: str) -> bool:
    """does deezer's artist match ours? a duo credit counts if deezer lists just one member,
    since deezer files "Erykah Badu & The Alchemist" albums under "Erykah Badu"."""
    deezer_key = to_name_key(deezer_artist)
    for name in split_artist_names(our_artist):
        if fuzz.ratio(to_name_key(name), deezer_key) >= ARTIST_NAME_THRESHOLD:
            return True
    return False


def title_score(our_title: str, deezer_title: str) -> float:
    """how close two titles are (0-100), ignoring anything in brackets on either side, so
    "Painkiller" still matches "Painkiller (feat. Denzel Curry)". the full titles are compared
    too, and the better of the two scores counts."""
    full_score = fuzz.ratio(to_name_key(our_title), to_name_key(deezer_title))
    our_short = BRACKETED_PART_PATTERN.sub("", our_title)
    deezer_short = BRACKETED_PART_PATTERN.sub("", deezer_title)
    short_score = fuzz.ratio(to_name_key(our_short), to_name_key(deezer_short))
    return max(full_score, short_score)


def to_searchable_title(artist: str, title: str) -> str:
    """fantano's titles call self-titled albums "Self-Titled", but stores use the artist's name:

        ("Weezer", "Self-Titled (Gold)") -> "Weezer (Gold)"
        ("Chat Pile", "Who Loves the Sun") -> "Who Loves the Sun"
    """
    return SELF_TITLED_PATTERN.sub(artist, title)


# --- picking the right result ---

def pick_artist_photo(artist_name: str, results: list[dict]) -> str | None:
    """the photo url for this artist, or None. among results named like the artist with a real
    photo, the one with the most fans wins, so the famous "Miley Cyrus" beats an empty duplicate."""
    best_photo = None
    most_fans = -1
    for result in results:
        if fuzz.ratio(to_name_key(artist_name), to_name_key(result["name"])) < ARTIST_NAME_THRESHOLD:
            continue
        if not is_real_image(result.get("picture_xl")):
            continue
        if result.get("nb_fan", 0) > most_fans:
            most_fans = result.get("nb_fan", 0)
            best_photo = result["picture_xl"]
    return best_photo


def pick_cover(artist_name: str, title: str, results: list[dict]) -> str | None:
    """the cover url for this album or song, or None. works for both album and track results:
    an album result has its cover on itself, a track result has it on its album."""
    best_cover = None
    best_score = 0
    for result in results:
        if not is_same_artist(artist_name, result["artist"]["name"]):
            continue
        score = title_score(title, result["title"])
        if score < TITLE_THRESHOLD:
            continue

        cover = result.get("cover_xl") or result.get("album", {}).get("cover_xl")
        if not is_real_image(cover):
            continue
        # strictly better only, so on a tie deezer's own ranking (the earlier result) wins
        if score > best_score:
            best_score = score
            best_cover = cover
    return best_cover


def find_artist_photo(artist_name: str) -> str | None:
    """the photo for this artist. a duo credit like "Erykah Badu & The Alchemist" has no photo
    of its own on deezer, so it falls back to the first member's photo."""
    photo_url = pick_artist_photo(artist_name, search_deezer("artist", artist_name))
    if photo_url:
        return photo_url

    # split_artist_names gives [full credit, member 1, member 2, ...]
    members = split_artist_names(artist_name)[1:]
    if not members:
        return None
    first_member = members[0]
    return pick_artist_photo(first_member, search_deezer("artist", first_member))


def find_cover(deezer_kind: str, artist_name: str, title: str) -> str | None:
    """the cover for this album (deezer_kind="album") or song ("track"). like photos, a duo
    credit gets a second try with just its first member, since searching
    "Denzel Curry & Kenneth Blume ii" finds nothing but "Denzel Curry ii" does."""
    searchable_title = to_searchable_title(artist_name, title)
    results = search_deezer(deezer_kind, f"{artist_name} {searchable_title}")
    cover_url = pick_cover(artist_name, searchable_title, results)
    if cover_url:
        return cover_url

    members = split_artist_names(artist_name)[1:]
    if not members:
        return None
    results = search_deezer(deezer_kind, f"{members[0]} {searchable_title}")
    # still checked against the full credit, and is_same_artist accepts any one member
    return pick_cover(artist_name, searchable_title, results)


# --- filling in each table ---

def fill_artist_photos(conn) -> list[str]:
    """finds a photo for every artist without one. returns the names that got nothing."""
    with conn.cursor() as cur:
        cur.execute(MISSING_ARTIST_PHOTOS_SQL)
        artists = cur.fetchall()

    missing = []
    for artist in artists:
        photo_url = find_artist_photo(artist["name"])
        if photo_url is None:
            missing.append(artist["name"])
            continue
        with conn.cursor() as cur:
            cur.execute("UPDATE artists SET image_url = %s WHERE id = %s", (photo_url, artist["id"]))
        conn.commit()

    print(f"artist photos: {len(artists) - len(missing)}/{len(artists)} found")
    return missing


def fill_covers(conn, table: str, missing_sql: str, deezer_kind: str) -> list[str]:
    """finds a cover for every release (deezer_kind="album") or track (deezer_kind="track")
    without one. returns "artist - title" for each one that got nothing."""
    with conn.cursor() as cur:
        cur.execute(missing_sql)
        rows = cur.fetchall()

    missing = []
    for row in rows:
        cover_url = find_cover(deezer_kind, row["artist"], row["title"])
        if cover_url is None:
            missing.append(f"{row['artist']} - {row['title']}")
            continue
        with conn.cursor() as cur:
            # the table name is one of two fixed strings from main(), never outside input
            cur.execute(f"UPDATE {table} SET cover_url = %s WHERE id = %s", (cover_url, row["id"]))
        conn.commit()

    print(f"{table} covers: {len(rows) - len(missing)}/{len(rows)} found")
    return missing


# --- running the stage ---

def main() -> None:
    MISSING_IMAGES_FILE.parent.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        missing = {
            "artists": fill_artist_photos(conn),
            "releases": fill_covers(conn, "releases", MISSING_RELEASE_COVERS_SQL, "album"),
            "tracks": fill_covers(conn, "tracks", MISSING_TRACK_COVERS_SQL, "track"),
        }

    MISSING_IMAGES_FILE.write_text(json.dumps(missing, ensure_ascii=False, indent=2))
    print(f"everything without an image is listed in {MISSING_IMAGES_FILE.relative_to(DATA_DIR.parent)}")


if __name__ == "__main__":
    main()
