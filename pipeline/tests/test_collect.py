"""tests for collect.py (stage 1): reading the type, subject, and duration of a video.

every title here is a real one from the channel, including the ones that broke earlier
versions of the regex (soundtrack reviews, "Artist- Title" without a space, "Jay-Z").
"""

import pytest

from collect import classify_title, parse_duration, parse_subject


@pytest.mark.parametrize("title, expected_type", [
    ("SZA - SOS ALBUM REVIEW", "album_review"),
    ("Mk.gee - Two Star & the Dream Police EP REVIEW", "album_review"),
    ("Future & Metro Boomin - WE DONT TRUST YOU MIXTAPE REVIEW", "album_review"),
    ("Joji - Will He TRACK REVIEW", "track_review"),
    ('Drake - "Pop Style" and "One Dance" TRACK REVIEWS', "track_review"),
    ("Yeat & Drake, Falling in Reverse, Porter Robinson | Weekly Track Roundup: 9/20/26", "roundup"),
    # "SOUNDTRACK REVIEW" contains "TRACK REVIEW", but it's not a single-song review
    ("Charli XCX - Wuthering Heights SOUNDTRACK REVIEW", "other"),
    # "REVIEW" glued onto another word doesn't count
    ("YUNOREVIEW: my favorite albums", "other"),
    ("3 NEW ALBUMS I LOVE", "other"),
])
def test_classify_title(title, expected_type):
    assert classify_title(title) == expected_type


@pytest.mark.parametrize("title, expected_subject", [
    ("SZA - SOS ALBUM REVIEW", ("SZA", "SOS")),
    ("Tyler, The Creator - CHROMAKOPIA ALBUM REVIEW", ("Tyler, The Creator", "CHROMAKOPIA")),
    # older titles have no space before the dash
    ("Tame Impala- Innerspeaker ALBUM REVIEW", ("Tame Impala", "Innerspeaker")),
    ("The Knife- Tomorrow, In a Year Album Review", ("The Knife", "Tomorrow, In a Year")),
    # the dash inside "Jay-Z" has no space after it, so it isn't the separator
    ("Jay-Z - The Blueprint ALBUM REVIEW", ("Jay-Z", "The Blueprint")),
    ("Joji - Will He TRACK REVIEW", ("Joji", "Will He")),
    # doesn't fit the pattern, so no guess
    ('Drake - "Pop Style" and "One Dance" TRACK REVIEWS', (None, None)),
    ("I'm moving to a new studio", (None, None)),
])
def test_parse_subject(title, expected_subject):
    assert parse_subject(title) == expected_subject


@pytest.mark.parametrize("iso_duration, expected_seconds", [
    ("PT12M34S", 754),
    ("PT1H2M3S", 3723),
    ("PT45S", 45),
    ("PT3H", 10800),
    ("P1DT2H", 93600),
    ("P0D", 0),
])
def test_parse_duration(iso_duration, expected_seconds):
    assert parse_duration(iso_duration) == expected_seconds


def test_parse_duration_rejects_garbage():
    with pytest.raises(ValueError):
        parse_duration("12 minutes")
