"""reads the facts Fantano writes in a fixed format at the bottom of his video descriptions. no ai.

a review's description ends like this:     a roundup's description has lists like this:

    FAV TRACKS: DIFFERENT RELIGION, ...        !!!BEST TRACKS THIS WEEK!!!
    LEAST FAV TRACK: ORBIT                     Godflesh - Master and Slave
    5/10                                       ...meh...
                                               Troye Sivan - Party
                                               !!!WORST TRACKS THIS WEEK!!!
                                               2hollis - Sex

he's kept this format for years (on the newest 1,000 videos: 97% of reviews have a score, 93%
have fav tracks, and every roundup has its lists), so plain regex reads it exactly. that's free,
and it can't make anything up the way an ai could.

every function here is pure: description text in, facts out. when a pattern doesn't match,
the answer is empty (None or []). we never guess. extract.py (stage 3) is the only caller.
"""

import re

# reviews.score_text in the database is VARCHAR(32)
SCORE_MAX_LENGTH = 32

# the score is everything up to "/10" on its line. for albums he loved, a link follows on the
# same line ("8/10 https://theneedledrop.com/loved-list/2025/"), so we stop right after "/10"
SCORE_PATTERN = re.compile(r"^(.*?\S/10)(?=\s|$)")

# the header lines that start each roundup list. they allow for the typos seen in real
# descriptions, like "!!!BEST TRACK THIS WEEK!!!", a missing closing "!!!", and "…meh…" vs "...meh..."
ROUNDUP_SECTION_HEADERS = [
    ("best", re.compile(r"^!+\s*BEST TRACKS? THIS WEEK", re.IGNORECASE)),
    ("meh", re.compile(r"^[.…]+\s*meh\s*[.…]+$", re.IGNORECASE)),
    ("worst", re.compile(r"^!+\s*WORST TRACKS? THIS WEEK", re.IGNORECASE)),
]

# " ft. Denzel Curry" or " feat. Denzel Curry" at the end of a track title
FEATURED_PATTERN = re.compile(r"\s+(?:ft|feat)\.\s+(.+)$", re.IGNORECASE)


def clean_lines(description: str) -> list[str]:
    """splits a description into lines, with the whitespace trimmed off each one."""
    return [line.strip() for line in description.splitlines()]


# --- album and track reviews ---

def parse_score(description: str) -> str | None:
    """finds his score, exactly as he wrote it: "5/10", "8/10", "CLASSIC/10".

    a double album gets two ("HABIBTI: 7/10" and "MAID OF HONOUR: 6/10"), which are joined
    with " · ". returns None if there's no score, or if it's too long for the database
    column (one description has glitch-art text before its "/10").
    """
    scores = []
    for line in clean_lines(description):
        # a link line can contain "/10" too, so skip anything that is itself a url
        if line.startswith("http"):
            continue
        match = SCORE_PATTERN.match(line)
        if match:
            scores.append(match[1])

    score_text = " · ".join(scores)
    if 0 < len(score_text) <= SCORE_MAX_LENGTH:
        return score_text
    return None


def parse_track_list(description: str, prefix: str) -> list[str]:
    """the comma-separated tracks after "FAV TRACKS:" (prefix "FAV") or "LEAST FAV TRACK:"
    (prefix "LEAST FAV"), e.g. "FAV TRACKS: DIFFERENT RELIGION, REDLIGHTS" ->
    ["DIFFERENT RELIGION", "REDLIGHTS"]. returns [] if the line isn't there."""
    # ^ pins the prefix to the start of the line, so "FAV" doesn't also match "LEAST FAV TRACK:"
    pattern = rf"^{prefix} TRACKS?:\s*(.+)$"
    for line in clean_lines(description):
        match = re.match(pattern, line, re.IGNORECASE)
        if match:
            tracks = [track.strip() for track in match[1].split(",")]
            return [track for track in tracks if track]
    return []


def parse_review(description: str) -> dict:
    """everything we read from a review's description, as one dict:
    {"score_text": "5/10", "fav_tracks": [...], "least_fav": [...]}."""
    return {
        "score_text": parse_score(description),
        "fav_tracks": parse_track_list(description, "FAV"),
        "least_fav": parse_track_list(description, "LEAST FAV"),
    }


# --- weekly track roundups ---

def find_section_header(line: str) -> str | None:
    """if this line starts a roundup list, returns which one ("best", "meh", or "worst").
    otherwise None."""
    for section, header_pattern in ROUNDUP_SECTION_HEADERS:
        if header_pattern.match(line):
            return section
    return None


def split_track_line(line: str) -> dict | None:
    """splits one roundup list line into its parts:

        "Joy Crookes - Painkiller ft. Denzel Curry"
        -> {"artist": "Joy Crookes", "title": "Painkiller", "featured": ["Denzel Curry"]}

    returns None if the line isn't "artist - title" shaped.
    """
    # partition splits on the first " - " only, so a dash inside the title stays in the title
    artist, separator, title = line.partition(" - ")
    if not separator or not artist.strip() or not title.strip():
        return None

    featured_artists = []
    featured_match = FEATURED_PATTERN.search(title)
    if featured_match:
        # "Bill Callahan & Chris Thile" or "A, B" -> one entry per artist
        names = re.split(r",\s*|\s+&\s+", featured_match[1])
        featured_artists = [name.strip() for name in names if name.strip()]
        # cut the "ft. ..." part off the title
        title = title[:featured_match.start()]

    return {"artist": artist.strip(), "title": title.strip(), "featured": featured_artists}


def parse_roundup(description: str) -> dict:
    """reads the best / meh / worst lists from a roundup's description, top to bottom.

    each track comes back with its artist, title, featured artists, and verdict (the list it
    was on). lines under a header that don't look like "artist - title" land in "unparsed",
    so nothing gets guessed:

        {"tracks": [{"artist": ..., "title": ..., "featured": [...], "verdict": "best"}, ...],
         "unparsed": [...]}
    """
    tracks = []
    unparsed_lines = []
    current_section = None  # stays None until we hit the first list header

    for line in clean_lines(description):
        section = find_section_header(line)
        if section:
            current_section = section
            continue

        # the "=====" divider comes right after the lists, so we're done
        if line.startswith("==="):
            break

        # skip anything before the first header, blank lines, and the link under each track
        if current_section is None or not line or line.startswith("http"):
            continue

        track = split_track_line(line)
        if track:
            tracks.append({**track, "verdict": current_section})
        else:
            unparsed_lines.append(line)

    return {"tracks": tracks, "unparsed": unparsed_lines}
