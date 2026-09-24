"""Sends a HTTP request to Gemini's API w/ prompt, text (numbered transcript), and schema we expect enforced by Gemini"""


import json
import os
import time

import httpx
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "https://generativelanguage.googleapis.com/v1beta"
MAX_ATTEMPTS = 4


class LLMUnavailable(Exception):
    """Temporary: rate limit, daily quota, or server trouble. The caller should stop and retry later."""


def generate_json(prompt: str, text: str, schema: dict) -> dict:
    """Sends instructions + input text to LLM; expecting a dict back

    Raises LLMUnavailable for temporary problem, and ValueError when the answer
    itself is unusable (mark that video 'failed').
    """
    model = os.environ["GEMINI_MODEL"]
    body = {
        "systemInstruction": {"parts": [{"text": prompt}]},          # the rules
        "contents": [{"role": "user", "parts": [{"text": text}]}],    # the transcript
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,                  # the API forces this exact shape
            "thinkingConfig": {"thinkingLevel": "minimal"},  # extraction, not puzzles: save tokens
        },
    }
    headers = {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}
    url = f"{API}/models/{model}:generateContent"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        # Attempt to call Gemini's generateContent endpiont
        try:
            r = httpx.post(url, json=body, headers=headers, timeout=120)
        except httpx.TransportError as e:                  
            error = f"network: {e}"
        # Otherwise if not a network error (either client success (200) or client error (400))
        else:
            # Raise status code
            if r.status_code == 200:
                return _parse(r.json())
            if r.status_code != 429 and r.status_code < 500:
                raise RuntimeError(f"Gemini {r.status_code}: {r.text[:500]}")
            
            error = f"HTTP {r.status_code}"                
        if attempt < MAX_ATTEMPTS:
             # 10s, 20s, 40s: "exponential backoff"
            wait = 10 * 2 ** (attempt - 1)                
            print(f"  Gemini {error}; retrying in {wait}s")
            time.sleep(wait)
    raise LLMUnavailable(f"Gemini still unavailable after {MAX_ATTEMPTS} attempts ({error})")


def _parse(response: dict) -> dict:
    """Pull the JSON text out of Gemini's envelope and check the answer finished properly."""
    candidates = response.get("candidates") or []
    if not candidates:
        raise ValueError(f"no answer (blocked?): {response.get('promptFeedback')}")
    c = candidates[0]
    if c.get("finishReason") != "STOP":                    # e.g. MAX_TOKENS = cut off mid-JSON
        raise ValueError(f"answer didn't finish: {c.get('finishReason')}")
    text = "".join(p.get("text", "") for p in c["content"]["parts"])
    return json.loads(text)


if __name__ == "__main__":
    schema = {
        "type": "object",
        "properties": {"artists": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "line": {"type": "integer"}},
            "required": ["name", "line"],
        }}},
        "required": ["artists"],
    }
    print(generate_json(
        prompt="List every musical artist mentioned, with the line number where it's said.",
        text="[44 @ 3:10] which honestly gives me some frank ocean\n[45 @ 3:12] blonde vibes, unlike drake",
        schema=schema,
    ))
