"""Shared LLM client, retry logic, and model configuration."""

import json
import os
import random
import re
import threading
import time

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

# Retry configuration
MAX_RETRIES = 5
BASE_DELAY = 3  # seconds

MODEL = "gemini-3-flash-preview"

# Concurrency limiter — prevents thundering-herd 429s when many threads
# call Gemini simultaneously (e.g. parallel job evaluation).
# Gemini allows ~1000 RPM; with ~3-5s latency per call, 30 concurrent
# requests ≈ 360-600 RPM — well within limits.
_gemini_semaphore = threading.Semaphore(30)


def create_client() -> genai.Client:
    """Create a Gemini client."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable not set")
    return genai.Client(api_key=api_key)


def call_gemini(
    client: genai.Client,
    prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> str:
    """Make a Gemini API call with retry logic.

    Retries on 429 (rate limit) and 503 (overloaded) with exponential backoff.
    """
    last_exception: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            with _gemini_semaphore:
                response = client.models.generate_content(
                    model=MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=max_tokens,
                    ),
                )
            return response.text or ""
        except ServerError as e:
            last_exception = e
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2**attempt) + random.uniform(0, 1)  # noqa: S311
                time.sleep(delay)
        except ClientError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                last_exception = e
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2**attempt) + random.uniform(0, 1)  # noqa: S311
                    time.sleep(delay)
            else:
                raise

    raise last_exception  # type: ignore[misc]


def parse_json(text: str) -> dict | list:
    """Extract and parse JSON from an LLM response that may contain markdown fences.

    Handles responses like:
        ```json\n{...}\n```
        ```\n[...]\n```
        Some text {json} more text
        Raw JSON
    """
    if not text:
        raise ValueError("Empty response from API")

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    stripped = re.sub(r"```(?:json)?\s*\n?", "", text).strip()

    # Try parsing the stripped text directly
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Try extracting the outermost JSON object { ... }
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Try extracting a JSON array [ ... ]
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from response: {text[:200]}")
