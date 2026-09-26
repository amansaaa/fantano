"""tests for load.py (stage 4): the name matching rule.

the musicbrainz results here are trimmed copies of real searches made while building this.
each one is a case the rule has to get right: a clear winner, two bands with the same name,
a top hit that's a different band, and an official name that differs from what he said.
"""

import pytest

from load import find_reviewed_match, is_named_like, pick_musicbrainz_artist, to_name_key


def make_result(name: str, score: int, aliases: list[str] | None = None) -> dict:
    """one musicbrainz search result, in the same shape the api sends back."""
    return {"id": f"mbid-{to_name_key(name)}-{score}", "name": name, "score": score,
            "aliases": [{"name": alias} for alias in aliases or []]}


# --- names -> keys ---

@pytest.mark.parametrize("name, expected_key", [
    ("A$AP Rocky", "asaprocky"),
    ("ASAP Rocky", "asaprocky"),
    ("Björk", "bjork"),
    ("D.R.A.M.", "dram"),
    ("Tyler, The Creator", "tylerthecreator"),
])
def test_to_name_key(name, expected_key):
    assert to_name_key(name) == expected_key


# --- rule 1: artists he reviewed ---

REVIEWED_NAMES = ["Björk", "ScHoolboy Q", "The Velvet Underground & Nico", "Ana Frango Elétrico"]
REVIEWED_KEYS = [to_name_key(name) for name in REVIEWED_NAMES]


@pytest.mark.parametrize("spoken_name, expected_match", [
    # comes back spelled the way the review title spells it
    ("Bjork", "Björk"),
    ("Schoolboy Q", "ScHoolboy Q"),
    # a caption typo is still close enough
    ("Ana Frango Eléctrico", "Ana Frango Elétrico"),
    # scores 91: close, but a different credit. this is why the threshold is 95 and not 90
    ("The Velvet Underground", None),
    ("Frank Ocean", None),
])
def test_find_reviewed_match(spoken_name, expected_match):
    assert find_reviewed_match(spoken_name, REVIEWED_NAMES, REVIEWED_KEYS) == expected_match


# --- rule 2: MusicBrainz ---

def test_is_named_like_checks_aliases():
    jorge_ben_jor = make_result("Jorge Ben Jor", 100, aliases=["Jorge Ben", "Jorge Benjor"])
    assert is_named_like("Jorge Ben", jorge_ben_jor)
    assert not is_named_like("Cold", make_result("Cold Chisel", 100))


def test_clear_winner_is_accepted_with_the_official_name():
    results = [make_result("Bolt Thrower", 100), make_result("Bolt Thrower II", 74)]
    artist, reason = pick_musicbrainz_artist("Bolt Thrower", results)
    assert artist == {"name": "Bolt Thrower", "mbid": "mbid-boltthrower-100"}
    assert reason is None


def test_bigger_credit_with_the_same_start_is_not_a_rival():
    results = [make_result("Nick Cave", 100), make_result("Nick Cave & the Bad Seeds", 93)]
    artist, _ = pick_musicbrainz_artist("Nick Cave", results)
    assert artist["name"] == "Nick Cave"


def test_same_named_artists_far_behind_dont_block_a_famous_one():
    results = [make_result("XTC", 100), make_result("XTC", 67), make_result("XTC", 67)]
    artist, _ = pick_musicbrainz_artist("XTC", results)
    assert artist["name"] == "XTC"


def test_official_name_is_used_when_he_says_it_differently():
    results = [make_result("The Velvet Underground", 100), make_result("Velvet Underground", 75)]
    artist, _ = pick_musicbrainz_artist("Velvet Underground", results)
    assert artist["name"] == "The Velvet Underground"


def test_two_artists_with_the_same_name_is_a_coin_flip_so_it_is_dropped():
    results = [make_result("Repentance", 100), make_result("Repentance", 97)]
    artist, reason = pick_musicbrainz_artist("Repentance", results)
    assert artist is None
    assert reason == "2 musicbrainz artists named like this, no clear winner"


def test_top_hit_named_differently_is_ignored():
    # the top hit for "Cold" is Cold Chisel. the real "Cold" only scores 94, so nothing is accepted
    results = [make_result("Cold Chisel", 100), make_result("Cold", 94), make_result("CoLD SToRAGE", 92)]
    artist, reason = pick_musicbrainz_artist("Cold", results)
    assert artist is None
    assert reason == "best musicbrainz match only scores 94"


def test_no_results_is_dropped():
    # a misspelled name ("Christian Lee Hudson" for Christian Lee Hutson) finds nothing
    artist, reason = pick_musicbrainz_artist("Christian Lee Hudson", [])
    assert artist is None
    assert reason == "no musicbrainz artist with that name"
