"""the only file that knows which ai we use (Gemini, free tier). everything else just calls generate_json().

generate_json(prompt, text, schema) sends one request to Gemini's api and hands back its answer
as a dict:
  - prompt:  the instructions (e.g. the contents of prompts/review.md)
  - text:    the input to work on (e.g. the numbered transcript extract.py builds)
  - schema:  the exact json shape the answer has to have. the api enforces it

it knows nothing about Fantano, artists, or quotes, that's all in the prompt and in extract.py.
switching to a different ai means rewriting this file and nothing else.

quick smoke test:  uv run llm.py
"""

import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

# load .env ourselves instead of counting on db.py being imported first
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta"

# total tries for a request that keeps hitting rate limits or server errors
MAX_ATTEMPTS = 4

# waits between tries: 10s, then 20s, then 40s ("exponential backoff")
FIRST_RETRY_WAIT_SECONDS = 10

# long transcripts can take a while to answer
REQUEST_TIMEOUT_SECONDS = 120


class LLMUnavailable(Exception):
    """a temporary problem: rate limit, daily quota, or Gemini's servers acting up. whoever
    called us should stop the run and try again later (extract.py leaves videos 'pending')."""


def build_request_body(prompt: str, text: str, schema: dict) -> dict:
    """the json body Gemini's generateContent endpoint expects."""
    return {
        # the rules the model follows
        "systemInstruction": {"parts": [{"text": prompt}]},
        # the input it works on
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {
            # answer with json only, in exactly this shape
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
            # this is reading and extracting, not puzzle solving, so skip the extra thinking
            # and save free quota
            "thinkingConfig": {"thinkingLevel": "minimal"},
        },
    }


def generate_json(prompt: str, text: str, schema: dict) -> dict:
    """sends `prompt` + `text` to Gemini and returns its answer as a dict shaped like `schema`.

    what happens when things go wrong:
      - 429 (rate limit), 5xx (server trouble), or a network blip: wait and retry, up to 4
        tries. if it still fails, raise LLMUnavailable
      - 400 / 403 / 404 (bad key, wrong model name, bad schema): our own mistake, retrying
        won't fix it, so raise RuntimeError right away with Google's message
      - an answer that got blocked or cut off: raise ValueError (the caller marks that one
        video 'failed')
    """
    model = os.environ["GEMINI_MODEL"]
    url = f"{GEMINI_API_URL}/models/{model}:generateContent"
    # the key goes in a header, not the url, so it never ends up in error messages
    headers = {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}
    body = build_request_body(prompt, text, schema)

    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = httpx.post(url, json=body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        except httpx.TransportError as error:
            # couldn't reach Google at all (wifi dropped, dns failed...)
            last_error = f"network: {error}"
        else:
            if response.status_code == 200:
                return read_answer(response.json())

            is_retryable = response.status_code == 429 or response.status_code >= 500
            if not is_retryable:
                raise RuntimeError(f"Gemini {response.status_code}: {response.text[:500]}")
            last_error = f"HTTP {response.status_code}"

        if attempt < MAX_ATTEMPTS:
            wait_seconds = FIRST_RETRY_WAIT_SECONDS * 2 ** (attempt - 1)
            print(f"  Gemini {last_error}; retrying in {wait_seconds}s")
            time.sleep(wait_seconds)

    raise LLMUnavailable(f"Gemini still unavailable after {MAX_ATTEMPTS} attempts ({last_error})")


def read_answer(response: dict) -> dict:
    """digs the answer out of Gemini's response and turns it into a dict. the answer sits a
    few layers deep, as a json string:

        {"candidates": [{"content": {"parts": [{"text": "{\\"artists\\": [...]}"}]},
                         "finishReason": "STOP"}]}

    raises ValueError if there's no answer (blocked) or it didn't finish (e.g. MAX_TOKENS,
    which means it got cut off mid-json). a broken json string raises json.JSONDecodeError,
    which is a ValueError too.
    """
    candidates = response.get("candidates") or []
    if not candidates:
        raise ValueError(f"no answer (blocked?): {response.get('promptFeedback')}")

    first_candidate = candidates[0]
    if first_candidate.get("finishReason") != "STOP":
        raise ValueError(f"answer didn't finish: {first_candidate.get('finishReason')}")

    answer_text = "".join(part.get("text", "") for part in first_candidate["content"]["parts"])
    return json.loads(answer_text)


def run_smoke_test() -> None:
    """sends a tiny two-line transcript and prints the answer. a 5-second check that the key,
    the model name, and the connection all work."""
    artists_schema = {
        "type": "object",
        "properties": {"artists": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "line": {"type": "integer"}},
            "required": ["name", "line"],
        }}},
        "required": ["artists"],
    }
    answer = generate_json(
        prompt="List every musical artist mentioned, with the line number where it's said.",
        text="[44 @ 3:10] which honestly gives me some frank ocean\n[45 @ 3:12] blonde vibes, unlike drake",
        schema=artists_schema,
    )
    print(answer)


# only runs for `uv run llm.py`, not when extract.py imports generate_json
if __name__ == "__main__":
    run_smoke_test()
