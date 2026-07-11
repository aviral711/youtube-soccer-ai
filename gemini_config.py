# gemini_config.py
#
# Configures the Gemini client and generates a YouTube Shorts script from a
# match_summary.json. Uses Google's unified GenAI SDK (`google-genai`):
#
#     pip install google-genai
#
# Auth: set your API key in the environment before running, e.g.
#     export GEMINI_API_KEY="your-key"     (or GOOGLE_API_KEY)
# Get a key from Google AI Studio: https://aistudio.google.com/app/apikey

import os
import json
import time
import random
import argparse

from dotenv import load_dotenv
from pydantic import BaseModel
from google import genai
from google.genai import types
from google.genai import errors as genai_errors

from ai_prompt import SYSTEM_INSTRUCTION, build_prompt, load_match_summary

# Load the project .env (sitting next to this file) regardless of the current
# working directory, so non-interactive runs (cron, Task Scheduler) get the key
# too. Real environment variables still take precedence (load_dotenv won't
# override them), so you can also export the key if you prefer.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# Model is overridable via env so you can swap flash/pro without code changes.
# "gemini-flash-latest" always points at the current flash model, which is fast,
# cheap, and well-suited to short creative scripts (and avoids the "model no
# longer available to new users" breakage that pinned older versions hit).
MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

# Slightly high temperature for lively copy, but the system rules keep it factual.
TEMPERATURE = float(os.environ.get("GEMINI_TEMPERATURE", "0.9"))

# Retry settings for transient API failures (all env-overridable).
MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "4"))
RETRY_BASE_DELAY = float(os.environ.get("GEMINI_RETRY_BASE_DELAY", "2.0"))
RETRY_MAX_DELAY = float(os.environ.get("GEMINI_RETRY_MAX_DELAY", "30.0"))
# HTTP status codes worth retrying: 429 rate limit + transient server errors.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class VideoScript(BaseModel):
    """Structured output contract for the generated script.

    Passed to Gemini as response_schema so the model is constrained to return
    exactly this shape (mirrors the fields described in ai_prompt.PROMPT_TEMPLATE).
    """
    title: str
    hook: str
    voiceover: str
    on_screen_text: list[str]
    caption: str
    hashtags: list[str]


def _api_key():
    """Read the API key from the environment (GEMINI_API_KEY or GOOGLE_API_KEY)."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError(
            "No API key found. Set GEMINI_API_KEY (or GOOGLE_API_KEY) in your "
            "environment. Get one at https://aistudio.google.com/app/apikey"
        )
    return key


def get_client():
    """Return a configured Gemini client."""
    return genai.Client(api_key=_api_key())


def generation_config():
    """Build the GenerateContentConfig: system rules + JSON-structured output."""
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=TEMPERATURE,
        response_mime_type="application/json",
        response_schema=VideoScript,
    )


def _is_retryable(exc):
    """True for transient failures worth retrying (rate limits, 5xx, network)."""
    if isinstance(exc, genai_errors.APIError):
        return getattr(exc, "code", None) in RETRYABLE_STATUS
    # Connection resets / timeouts from the underlying HTTP client.
    return isinstance(exc, (ConnectionError, TimeoutError))


def _generate_with_retry(client, prompt, config):
    """Call generate_content, retrying transient errors with exponential
    backoff + jitter. Permanent errors (bad request, auth, model 404) raise
    immediately."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return client.models.generate_content(
                model=MODEL_NAME, contents=prompt, config=config
            )
        except Exception as exc:
            if attempt >= MAX_RETRIES or not _is_retryable(exc):
                raise
            delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
            delay += random.uniform(0, delay * 0.25)  # jitter
            code = getattr(exc, "code", type(exc).__name__)
            print(
                f"[retry] transient error {code}; "
                f"attempt {attempt + 1}/{MAX_RETRIES}, waiting {delay:.1f}s"
            )
            time.sleep(delay)


def generate_script(match_summary, client=None):
    """Generate a Shorts script for one match.

    Args:
        match_summary: summary dict, or path to a match_summary.json file.
        client: optional pre-built genai.Client (a new one is created if omitted).
    Returns:
        dict matching the VideoScript schema.
    """
    client = client or get_client()
    prompt = build_prompt(match_summary)

    response = _generate_with_retry(client, prompt, generation_config())
    # response.text is the JSON string; response.parsed is the validated model.
    if getattr(response, "parsed", None) is not None:
        return response.parsed.model_dump()
    return json.loads(response.text)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a YouTube Shorts script from a match_summary.json."
    )
    parser.add_argument(
        "summary_path",
        help="Path to a match_summary.json file (from generate_summary.py).",
    )
    parser.add_argument(
        "-o", "--out",
        help="Optional path to write the script JSON. Prints to stdout if omitted.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    summary = load_match_summary(args.summary_path)
    script = generate_script(summary)

    output = json.dumps(script, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Wrote {args.out}")
    else:
        print(output)


if __name__ == "__main__":
    main()
