"""tests for extract.py (stage 3): building the ai's input and checking its answer.

the verification checks are the most important thing in the whole pipeline, since they decide
what counts as "he really said that". so every mistake the ai actually made while we built this
is a test here: copying example names from the prompt as fake connections, stitching two quotes
together, citing the wrong line, garbling "Björk", and linking an artist to themself.
"""

from extract import (
    build_review_ai_input,
    build_review_extraction,
    find_connection_problem,
    find_matching_fav_track,
    find_quote_problem,
    format_timestamp,
    format_transcript,
    normalize_text,
    parse_release_kind,
    split_artist_names,
    to_title_key,
)


def make_caption_lines(texts: list[str]) -> list[dict]:
    """fake caption lines in the same shape captions.py saves, 4 seconds apart."""
    return [{"line": number, "start": number * 4.0, "text": text} for number, text in enumerate(texts)]


# a made-up review transcript. line 8 is the only place an artist gets compared
REVIEW_CAPTIONS = make_caption_lines([
    "hi everyone fantano here the internet's busiest music nerd",           # 0
    "and it's time for a review of this new erica badu and the",             # 1
    "alchemist album before the world blows",                                # 2
    "her older records have just aged really well",                          # 3
    "the song red lights is maybe one of the few other tracks",              # 4
    "on this record i genuinely enjoy but it's not without its uh",          # 5
    "derivative elements as this song uh feels almost like the",             # 6
    "quirkier cousin to any number of uh mid",                               # 7
    "to late 70s abba songs following this we have",                         # 8
    "neon signs which is a solid duet",                                      # 9
    "and it feels like something out of a björk record",                     # 10
    "filler line eleven",                                                    # 11
    "filler line twelve",                                                    # 12
    "filler line thirteen",                                                  # 13
    "filler line fourteen",                                                  # 14
    "filler line fifteen",                                                   # 15
    "filler line sixteen",                                                   # 16
    "filler line seventeen",                                                 # 17
    "filler line eighteen",                                                  # 18
    "filler line nineteen",                                                  # 19
])

REVIEWED_ARTIST_NAMES = split_artist_names("Erykah Badu & The Alchemist")

ABBA_CONNECTION = {
    "artist": "ABBA", "heard_as": "abba", "about_artist": "Erykah Badu & The Alchemist",
    "label": "sounds_like", "line": 8,
    # the quote starts 4 lines before the name, which real quotes often do
    "quote": "the song Red Lights is maybe one of the few other tracks on this record I genuinely enjoy",
}


# --- building the ai's input ---

def test_format_timestamp():
    assert format_timestamp(190.2) == "3:10"
    assert format_timestamp(5) == "0:05"
    assert format_timestamp(3723) == "62:03"


def test_format_transcript_numbers_every_line():
    transcript = format_transcript(make_caption_lines(["hi everyone", "fantano here"]))
    assert transcript == "[0 @ 0:00] hi everyone\n[1 @ 0:04] fantano here"


def test_review_input_includes_fav_tracks_from_the_description():
    video = {"title": "Miley Cyrus - Bass Persuades ALBUM REVIEW",
             "description": "FAV TRACKS: DIFFERENT RELIGION, REDLIGHTS\n5/10"}
    ai_input = build_review_ai_input(video, make_caption_lines(["hi everyone"]))
    assert ai_input == ("TITLE: Miley Cyrus - Bass Persuades ALBUM REVIEW\n"
                        "FAV TRACKS: DIFFERENT RELIGION, REDLIGHTS\n"
                        "TRANSCRIPT:\n[0 @ 0:00] hi everyone")


def test_review_input_without_fav_tracks_leaves_the_line_out():
    video = {"title": "D'Angelo - Voodoo ALBUM REVIEW", "description": "CLASSIC/10"}
    assert "FAV TRACKS" not in build_review_ai_input(video, make_caption_lines(["hi"]))


# --- comparing text ---

def test_normalize_text():
    assert normalize_text("Beyoncé's, uh... FORMATION") == "beyonces uh formation"


def test_to_title_key_ignores_spacing_and_case():
    assert to_title_key("Red Lights") == to_title_key("REDLIGHTS") == "redlights"


def test_split_artist_names_includes_each_member():
    assert split_artist_names("Erykah Badu & The Alchemist") == \
        ["Erykah Badu & The Alchemist", "Erykah Badu", "The Alchemist"]


# --- checking connections ---

def test_real_connection_passes():
    assert find_connection_problem(ABBA_CONNECTION, REVIEW_CAPTIONS, REVIEWED_ARTIST_NAMES) is None


def test_invented_connection_is_dropped():
    # the ai copied an example from our own prompt and pinned it on a real line number
    fake_connection = {**ABBA_CONNECTION, "artist": "Frank Ocean", "heard_as": "frank ocean",
                       "line": 3, "quote": "I saw Frank Ocean memes all week"}
    problem = find_connection_problem(fake_connection, REVIEW_CAPTIONS, REVIEWED_ARTIST_NAMES)
    assert problem == "name 'frank ocean' not spoken near line 3"


def test_name_on_a_far_away_line_is_dropped():
    # abba is said on line 8, but the ai cited line 2
    wrong_line = {**ABBA_CONNECTION, "line": 2}
    assert find_connection_problem(wrong_line, REVIEW_CAPTIONS, REVIEWED_ARTIST_NAMES) is not None


def test_line_that_does_not_exist_is_dropped():
    made_up_line = {**ABBA_CONNECTION, "line": 1622}
    problem = find_connection_problem(made_up_line, REVIEW_CAPTIONS, REVIEWED_ARTIST_NAMES)
    assert problem == "line 1622 doesn't exist"


def test_garbled_heard_as_is_rescued_by_the_proper_spelling():
    # Gemini once sent heard_as with a broken character, for a caption that clearly says "Björk"
    bjork = {"artist": "Björk", "heard_as": "Bj\x96rk", "about_artist": "Erykah Badu",
             "label": "sounds_like", "line": 10, "quote": "it feels like something out of a Björk record"}
    assert find_connection_problem(bjork, REVIEW_CAPTIONS, REVIEWED_ARTIST_NAMES) is None


def test_connection_to_one_member_of_the_reviewed_duo_is_a_self_link():
    self_link = {**ABBA_CONNECTION, "artist": "Erykah Badu", "heard_as": "erica badu", "line": 1,
                 "quote": "a review of this new erica badu and the alchemist album"}
    problem = find_connection_problem(self_link, REVIEW_CAPTIONS, REVIEWED_ARTIST_NAMES)
    assert problem == "'Erykah Badu' is the artist being discussed (self-link)"


def test_unknown_label_is_dropped():
    made_up_label = {**ABBA_CONNECTION, "label": "vibes"}
    assert find_connection_problem(made_up_label, REVIEW_CAPTIONS, REVIEWED_ARTIST_NAMES) == "unknown label 'vibes'"


# --- checking quotes ---

def test_real_quote_passes():
    assert find_quote_problem("feels almost like the quirkier cousin", 7, REVIEW_CAPTIONS) is None


def test_paraphrased_quote_is_dropped():
    paraphrase = "it sounds a lot like a weirder version of classic seventies abba music"
    assert find_quote_problem(paraphrase, 7, REVIEW_CAPTIONS) == "quote not found near line 7"


def test_real_quote_cited_far_from_where_it_was_said_is_dropped():
    assert find_quote_problem("feels almost like the quirkier cousin", 19, REVIEW_CAPTIONS) is not None


def test_empty_quote_is_dropped():
    assert find_quote_problem("", 0, REVIEW_CAPTIONS) == "quote is empty"


# --- the rest of the review extraction ---

def test_find_matching_fav_track_allows_spelling_drift():
    fav_tracks = ["DIFFERENT RELIGION", "REDLIGHTS", "WITCH DOCTOR"]
    assert find_matching_fav_track("Red Lights", fav_tracks) == "REDLIGHTS"
    # a caption typo
    assert find_matching_fav_track("Witchd Doctor", fav_tracks) == "WITCH DOCTOR"
    assert find_matching_fav_track("Orbit", fav_tracks) is None


def test_parse_release_kind():
    assert parse_release_kind("Mk.gee - Two Star EP REVIEW") == "ep"
    assert parse_release_kind("Joji - Will He TRACK REVIEW") == "track"
    assert parse_release_kind("Weekly Track Roundup: 9/20/26") is None


def test_build_review_extraction_keeps_good_items_and_drops_bad_ones():
    video = {
        "title": "Erykah Badu & The Alchemist - Before the World Blows ALBUM REVIEW",
        "description": "FAV TRACKS: REDLIGHTS\n6/10",
        "subject_artist": "Erykah Badu & The Alchemist",
        "subject_title": "Before the World Blows",
    }
    ai_answer = {
        "liked": False,
        "summary": "He finds it unfocused.",
        "pull_quote": {"text": "her older records have just aged really well", "line": 3},
        "connections": [
            ABBA_CONNECTION,
            {**ABBA_CONNECTION, "artist": "Frank Ocean", "heard_as": "frank ocean", "line": 3,
             "quote": "I saw Frank Ocean memes all week"},
        ],
        "track_takes": [
            {"track": "Red Lights", "line": 4, "quote": "the song red lights is maybe one of the few other tracks",
             "summary": "One of the few he enjoys."},
        ],
    }

    extraction, dropped_items = build_review_extraction(video, ai_answer, REVIEW_CAPTIONS)

    # facts from the title and the description
    assert extraction["kind"] == "album"
    assert extraction["artist"] == "Erykah Badu & The Alchemist"
    assert extraction["score_text"] == "6/10"
    # the real connection is kept, with its timestamp taken from the caption file (line 8 -> 32s)
    assert [connection["artist"] for connection in extraction["connections"]] == ["ABBA"]
    assert extraction["connections"][0]["start_s"] == 32
    # the take is linked to the fav track as the description spells it
    assert extraction["track_takes"][0]["fav_track"] == "REDLIGHTS"
    assert extraction["pull_quote"]["start_s"] == 12
    # the invented connection is dropped, with a reason
    assert [(item["kind"], item["item"]["artist"]) for item in dropped_items] == [("connection", "Frank Ocean")]
