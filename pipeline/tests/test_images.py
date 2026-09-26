"""tests for images.py (stage 5): picking the right deezer result for a photo or cover.

the cases come from real deezer searches: an empty duplicate "Miley Cyrus", "Materia" vs
"Materia 2", duo credits filed under one member, and self-titled albums.
"""

import pytest

from images import is_real_image, is_same_artist, pick_artist_photo, pick_cover, title_score, to_searchable_title

REAL_PHOTO = "https://cdn-images.dzcdn.net/images/artist/3be756289836/1000x1000-000000-80-0-0.jpg"
PLACEHOLDER_PHOTO = "https://cdn-images.dzcdn.net/images/artist//1000x1000-000000-80-0-0.jpg"


def make_album(title: str, artist: str, cover: str = REAL_PHOTO) -> dict:
    """one deezer album result, in the same shape the api sends back."""
    return {"title": title, "artist": {"name": artist}, "cover_xl": cover}


def test_placeholder_photo_is_not_real():
    assert is_real_image(REAL_PHOTO)
    assert not is_real_image(PLACEHOLDER_PHOTO)
    assert not is_real_image(None)


def test_most_popular_artist_with_a_real_photo_wins():
    results = [
        {"name": "Miley Cyrus", "nb_fan": 0, "picture_xl": PLACEHOLDER_PHOTO},
        {"name": "Miley Cyrus", "nb_fan": 7240978, "picture_xl": REAL_PHOTO},
        {"name": "Miley Cyrus Tribute", "nb_fan": 9999999, "picture_xl": "https://other.jpg"},
    ]
    assert pick_artist_photo("Miley Cyrus", results) == REAL_PHOTO


def test_differently_named_artist_gets_no_photo():
    results = [{"name": "Sleep & Dream Zone", "nb_fan": 60, "picture_xl": REAL_PHOTO}]
    assert pick_artist_photo("Sleep", results) is None


def test_duo_credit_matches_one_member():
    assert is_same_artist("Erykah Badu & The Alchemist", "Erykah Badu")
    assert is_same_artist("AZ Chike", "AzChike")
    assert not is_same_artist("Julia Holter", "Karaoke All Keys")


@pytest.mark.parametrize("our_title, deezer_title, is_match", [
    ("Painkiller", "Painkiller (feat. Denzel Curry)", True),
    ("Maverick “Almost Forever”", "Maverick “Almost Forever” EP", True),
    ("Sedition", "SEDITION", True),
    ("Who Loves the Sun", "Something Else Entirely", False),
])
def test_title_score(our_title, deezer_title, is_match):
    assert (title_score(our_title, deezer_title) >= 85) == is_match


def test_closest_title_wins_over_deezers_first_result():
    materia_2 = "https://materia-2.jpg"
    materia = "https://materia.jpg"
    results = [make_album("Materia 2", "Julia Holter", materia_2), make_album("Materia", "Julia Holter", materia)]
    assert pick_cover("Julia Holter", "Materia", results) == materia


def test_cover_by_another_artist_is_ignored():
    results = [make_album("Bass Persuades (Karaoke Version)", "Karaoke All Keys")]
    assert pick_cover("Miley Cyrus", "Bass Persuades", results) is None


def test_track_result_uses_its_albums_cover():
    track = {"title": "Your Ghost Again", "artist": {"name": "Mastodon"}, "album": {"cover_xl": REAL_PHOTO}}
    assert pick_cover("Mastodon", "YOUR GHOST AGAIN", [track]) == REAL_PHOTO


def test_self_titled_album_is_searched_by_the_artists_name():
    assert to_searchable_title("Weezer", "Self-Titled (Gold)") == "Weezer (Gold)"
    assert to_searchable_title("Chat Pile", "Who Loves the Sun") == "Who Loves the Sun"
