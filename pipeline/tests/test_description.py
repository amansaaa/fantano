"""tests for description.py: reading scores, fav tracks, and roundup lists from descriptions.

the examples are copied from real descriptions, including the formats that broke the first
version: loved albums with a link after the score, "CLASSIC/10", and the "…meh…" spellings.
"""

import pytest

from description import parse_review, parse_roundup, parse_score, parse_track_list, split_track_line

MILEY_REVIEW_DESCRIPTION = """Listen: https://www.youtube.com/watch?v=aWpw-Ynl0Yc
A pretty unfocused and mostly unmemorable album from Miley.
===================================
FAV TRACKS: DIFFERENT RELIGION, REDLIGHTS
LEAST FAV TRACK: ORBIT
MILEY - BASS PERSUADES / 2026 / ATLANTIC / POP ROCK, DANCE-POP
5/10
Y'all know this is just my opinion, right?"""

ROUNDUP_DESCRIPTION = """2026 FAV TRACKS PLAYLIST: https://music.apple.com/us/playlist/my-fav-singles-of-2026
!!!BEST TRACKS THIS WEEK!!!
Godflesh - Master and Slave
https://www.youtube.com/watch?v=b1gAkor2JgU
Joy Crookes - Painkiller ft. Denzel Curry
https://www.youtube.com/watch?v=yHcaZhCbNUA
…meh...
Yeat - MISS MY DAWG ft. Drake
Review: https://www.youtube.com/watch?v=JZnAfAAOMmM
!!!WORST TRACKS THIS WEEK
2hollis - Sex
===================================
Subscribe: http://bit.ly/1pBqGCN
Some - Line After The Divider"""


def test_parse_review_reads_all_three_facts():
    assert parse_review(MILEY_REVIEW_DESCRIPTION) == {
        "score_text": "5/10",
        "fav_tracks": ["DIFFERENT RELIGION", "REDLIGHTS"],
        "least_fav": ["ORBIT"],
    }


@pytest.mark.parametrize("description, expected_score", [
    ("5/10", "5/10"),
    # loved albums have a link on the same line. this was missed at first, dropping his favorites
    ("8/10 https://theneedledrop.com/loved-list/2025/", "8/10"),
    ("CLASSIC/10", "CLASSIC/10"),
    ("GIGGENS LOVES IT/10", "GIGGENS LOVES IT/10"),
    # a double album gets two scores
    ("HABIBTI: 7/10\nMAID OF: 6/10", "HABIBTI: 7/10 · MAID OF: 6/10"),
    # a url that happens to contain "/10" is not a score
    ("https://example.com/top/10", None),
    ("no score in here", None),
    # longer than the VARCHAR(32) database column
    ("THIS IS A VERY VERY VERY LONG JOKE SCORE/10", None),
])
def test_parse_score(description, expected_score):
    assert parse_score(description) == expected_score


def test_fav_prefix_does_not_match_the_least_fav_line():
    description = "LEAST FAV TRACK: ORBIT\nFAV TRACKS: REDLIGHTS"
    assert parse_track_list(description, "FAV") == ["REDLIGHTS"]
    assert parse_track_list(description, "LEAST FAV") == ["ORBIT"]


def test_missing_track_list_is_empty():
    assert parse_track_list("5/10", "FAV") == []


@pytest.mark.parametrize("line, expected_track", [
    ("Godflesh - Master and Slave",
     {"artist": "Godflesh", "title": "Master and Slave", "featured": []}),
    ("Joy Crookes - Painkiller ft. Denzel Curry",
     {"artist": "Joy Crookes", "title": "Painkiller", "featured": ["Denzel Curry"]}),
    ("Meshell Ndegeocello - With God on Our Side ft. Bill Callahan & Chris Thile",
     {"artist": "Meshell Ndegeocello", "title": "With God on Our Side", "featured": ["Bill Callahan", "Chris Thile"]}),
    # only the first " - " splits, so a dash in the title stays in the title
    ("@ - Bird - Remix", {"artist": "@", "title": "Bird - Remix", "featured": []}),
    ("HEALTH :: THOUGHT LEADER", None),
])
def test_split_track_line(line, expected_track):
    assert split_track_line(line) == expected_track


def test_parse_roundup_reads_every_list_in_order():
    roundup = parse_roundup(ROUNDUP_DESCRIPTION)
    tracks = [(track["artist"], track["title"], track["verdict"]) for track in roundup["tracks"]]
    assert tracks == [
        ("Godflesh", "Master and Slave", "best"),
        ("Joy Crookes", "Painkiller", "best"),
        ("Yeat", "MISS MY DAWG", "meh"),
        ("2hollis", "Sex", "worst"),
    ]


def test_parse_roundup_skips_links_and_stops_at_the_divider():
    roundup = parse_roundup(ROUNDUP_DESCRIPTION)
    all_titles = [track["title"] for track in roundup["tracks"]]
    # the line after "=====" isn't part of the lists
    assert "Line After The Divider" not in all_titles
    # "Review: https://..." isn't "artist - title" shaped, so it's kept aside instead of guessed
    assert roundup["unparsed"] == ["Review: https://www.youtube.com/watch?v=JZnAfAAOMmM"]


def test_parse_roundup_without_lists_is_empty():
    assert parse_roundup(MILEY_REVIEW_DESCRIPTION) == {"tracks": [], "unparsed": []}
