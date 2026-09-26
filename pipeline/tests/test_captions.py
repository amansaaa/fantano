"""tests for captions.py (stage 2): turning the caption library's output into numbered lines."""

from captions import to_caption_lines


def test_to_caption_lines_numbers_and_cleans_each_line():
    snippets = [
        {"text": "hi everyone\nfantano here", "start": 0.0, "duration": 3.1},
        {"text": "the internet's  busiest music nerd", "start": 3.456, "duration": 2.0},
    ]
    assert to_caption_lines(snippets) == [
        {"line": 0, "start": 0.0, "text": "hi everyone fantano here"},
        {"line": 1, "start": 3.46, "text": "the internet's busiest music nerd"},
    ]


def test_to_caption_lines_handles_an_empty_transcript():
    assert to_caption_lines([]) == []
