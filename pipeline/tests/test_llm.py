"""tests for llm.py: reading Gemini's answer, and what happens when a request fails.

no real requests are made. monkeypatch swaps httpx.post for a fake that returns whatever
response a test wants, and swaps time.sleep for a no-op so the retry waits don't slow tests down.
"""

import pytest

import llm


def make_gemini_response(answer_text: str, finish_reason: str = "STOP") -> dict:
    """a fake response in the same nested shape Gemini sends back."""
    return {"candidates": [{"finishReason": finish_reason, "content": {"parts": [{"text": answer_text}]}}]}


class FakeHttpResponse:
    """stands in for an httpx response: just a status code and a body."""

    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self.body = body or {}
        self.text = str(self.body)

    def json(self) -> dict:
        return self.body


@pytest.fixture
def fake_gemini(monkeypatch):
    """replaces the network with a list of responses to hand back one by one, and counts calls."""
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)

    queued_responses = []
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append(url)
        return queued_responses.pop(0)

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    return queued_responses, calls


# --- reading the answer ---

def test_read_answer_returns_the_json_as_a_dict():
    assert llm.read_answer(make_gemini_response('{"artists": []}')) == {"artists": []}


def test_blocked_answer_raises_value_error():
    with pytest.raises(ValueError, match="blocked"):
        llm.read_answer({"promptFeedback": {"blockReason": "SAFETY"}})


def test_cut_off_answer_raises_value_error():
    with pytest.raises(ValueError, match="didn't finish"):
        llm.read_answer(make_gemini_response('{"artists": [', finish_reason="MAX_TOKENS"))


def test_broken_json_raises_value_error():
    with pytest.raises(ValueError):
        llm.read_answer(make_gemini_response('{"artists": ['))


# --- retries and errors ---

def test_success_on_the_first_try(fake_gemini):
    queued_responses, calls = fake_gemini
    queued_responses.append(FakeHttpResponse(200, make_gemini_response('{"ok": true}')))
    assert llm.generate_json("prompt", "text", {"type": "object"}) == {"ok": True}
    assert len(calls) == 1


def test_rate_limit_is_retried_until_it_works(fake_gemini):
    queued_responses, calls = fake_gemini
    queued_responses.extend([FakeHttpResponse(429), FakeHttpResponse(503),
                             FakeHttpResponse(200, make_gemini_response('{"ok": true}'))])
    assert llm.generate_json("prompt", "text", {"type": "object"}) == {"ok": True}
    assert len(calls) == 3


def test_rate_limit_that_never_clears_raises_llm_unavailable(fake_gemini):
    queued_responses, calls = fake_gemini
    queued_responses.extend([FakeHttpResponse(429)] * llm.MAX_ATTEMPTS)
    with pytest.raises(llm.LLMUnavailable):
        llm.generate_json("prompt", "text", {"type": "object"})
    assert len(calls) == llm.MAX_ATTEMPTS


def test_our_own_mistake_fails_right_away_without_retrying(fake_gemini):
    # a wrong model name gives a 404. retrying a typo can't help
    queued_responses, calls = fake_gemini
    queued_responses.append(FakeHttpResponse(404, {"error": "model not found"}))
    with pytest.raises(RuntimeError, match="404"):
        llm.generate_json("prompt", "text", {"type": "object"})
    assert len(calls) == 1
