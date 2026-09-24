"""Read the description Fantano writes in a fixed format at the bottom.

Review description:                      Roundup description:
    FAV TRACKS: DIFFERENT RELIGION, ...      !!!BEST TRACKS THIS WEEK!!!
    LEAST FAV TRACK: ORBIT                   Godflesh - Master and Slave
    5/10                                     ...meh...
                                             Troye Sivan - Party
                                             !!!WORST TRACKS THIS WEEK!!!
                                             2hollis - Sex

The description stays consistent for almost all of his videos across the years depending on the format.
This allows us to avoid using an LLM which saves token usage, and ensures we don't hallunicate any data as we're using regex. 

Every function here is pure: description text in, facts out. If a pattern doesn't match, 
the result is empty (None or []) as we never guess.
"""

import re

# reviews.score_text is VARCHAR(32)
SCORE_MAX_LEN = 32  

# Splits description into lines and strips whitespace from each
def _lines(description: str) -> list[str]:
    return [line.strip() for line in description.splitlines()]


# --- Album and track reviews ---

# Pulls Fantano's score ("7/10) which is usualy on an individal line in the description
# Sometimes for albums he loved, he puts a URl next to the score; this regex handles that case
SCORE_RE = re.compile(r"^(.*?\S/10)(?=\s|$)")


def parse_score(description: str) -> str | None:
    """Scans description line by line, collects every score it finds and joins them into one string.
    
    This handles both the normal case of just one score for an album and a double album which
    has two ("HABIBTI: 7/10", "MAID OF HONOUR: 6/10"), joined with " · "."""
    scores = []
    for line in _lines(description):
        m = SCORE_RE.match(line)

        # If we found a score (not URL) then add to scores
        if m and not line.startswith("http"):
            scores.append(m[1])
    text = " · ".join(scores)
    return text if 0 < len(text) <= SCORE_MAX_LEN else None


def parse_track_list(description: str, label: str) -> list[str]:
    """Tracks after "FAV TRACKS:" or "LEAST FAV TRACK:" (label = "FAV" or "LEAST FAV")"""
    # ^ and $ anchor the whole line, so "FAV" doesn't also match the "LEAST FAV" line.
    pattern = rf"^{label} TRACKS?:\s*(.+)$"
    for line in _lines(description):
        m = re.match(pattern, line, re.IGNORECASE)
        if m:
            return [t.strip() for t in m[1].split(",") if t.strip()]
    return []


def parse_review(description: str) -> dict:
    return {
        "score_text": parse_score(description),
        "fav_tracks": parse_track_list(description, "FAV"),
        "least_fav": parse_track_list(description, "LEAST FAV"),
    }


# --- Weekly Track Roundups ---

# List of (name, pattern) pairs for each section used to detect which section the header is for
SECTION_MARKERS = [
    ("best", re.compile(r"^!+\s*BEST TRACKS? THIS WEEK", re.IGNORECASE)),
    ("meh", re.compile(r"^[.…]+\s*meh\s*[.…]+$", re.IGNORECASE)),
    ("worst", re.compile(r"^!+\s*WORST TRACKS? THIS WEEK", re.IGNORECASE)),
]

# Detects featured artist on a track title
FEAT_RE = re.compile(r"\s+(?:ft|feat)\.\s+(.+)$", re.IGNORECASE)


def split_track_line(line: str) -> dict | None:
    """ "Joy Crookes - Painkiller ft. Denzel Curry"
        -> {"artist": "Joy Crookes", "title": "Painkiller", "featured": ["Denzel Curry"]} """
    # Splits string into first occurence of " - " and wlays returns three pieces (artist, seperator, title)
    artist, sep, title = line.partition(" - ")
    if not sep or not artist.strip() or not title.strip():
        return None
    featured = []
    m = FEAT_RE.search(title)

    # Add featured artists if they exist
    if m:
        featured = [a.strip() for a in re.split(r",\s*|\s+&\s+", m[1]) if a.strip()]
        title = title[: m.start()]
    return {"artist": artist.strip(), "title": title.strip(), "featured": featured}


def parse_roundup(description: str) -> dict:
    """Roundup video descriptions follow a different format: this function handles that case.
    Tracks from the best / meh / worst lists, in order with each tagged with its review score."""
    tracks, unparsed, verdict = [], [], None
    for line in _lines(description):
        marker = next((name for name, rx in SECTION_MARKERS if rx.match(line)), None)

        # Found the header so we can update the verdict to that section 
        if marker:
            verdict = marker

        # "=====" line ends the lists
        elif line.startswith("==="):          
            break

        # Each track is followed by its link
        elif verdict and line and not line.startswith("http"):   
            track = split_track_line(line)
            if track:
                tracks.append({**track, "verdict": verdict})
            else:
                unparsed.append(line)
    return {"tracks": tracks, "unparsed": unparsed}
