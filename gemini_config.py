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
import re
import json
import time
import random
import functools
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

# Text-to-speech (voiceover) settings. gemini-3.1-flash-tts-preview is the
# latest dedicated TTS model; "Puck" is an upbeat prebuilt voice that suits
# hype-y sports recaps. TTS_STYLE is a natural-language delivery direction
# prepended to the narration. All env-overridable.
TTS_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview")
TTS_VOICE = os.environ.get("GEMINI_TTS_VOICE", "Puck")
TTS_STYLE = os.environ.get(
    "GEMINI_TTS_STYLE",
    "Narrate this soccer recap like a high-energy sports highlights announcer: "
    "fast, punchy pacing, rising excitement into the decisive moment. Pronounce "
    "player and team names in their correct native pronunciation.",
)

# Optional lexicon that maps exact names to a phonetic respelling, applied to the
# SPOKEN text only (real names stay intact in the script/on-screen fields). This
# is how you deterministically fix a name the TTS mispronounces: add an entry and
# re-run. Keys starting with "_" are ignored (use for notes).
PRONUNCIATION_FILE = os.environ.get("GEMINI_PRONUNCIATIONS", "pronunciations.json")


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


def _generate_with_retry(client, model, prompt, config):
    """Call generate_content, retrying transient errors with exponential
    backoff + jitter. Permanent errors (bad request, auth, model 404) raise
    immediately."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return client.models.generate_content(
                model=model, contents=prompt, config=config
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

    response = _generate_with_retry(client, MODEL_NAME, prompt, generation_config())
    # response.text is the JSON string; response.parsed is the validated model.
    if getattr(response, "parsed", None) is not None:
        return response.parsed.model_dump()
    return json.loads(response.text)


def generate_json(prompt, response_schema=None, model=None, client=None,
                  system_instruction=None):
    """Generic structured-JSON generation with retry (no scriptwriter persona).

    Returns the parsed object (dict) when a pydantic response_schema is given,
    otherwise the JSON-decoded response text.
    """
    client = client or get_client()
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=TEMPERATURE,
        response_mime_type="application/json",
        response_schema=response_schema,
    )
    response = _generate_with_retry(client, model or MODEL_NAME, prompt, config)
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        return parsed.model_dump() if hasattr(parsed, "model_dump") else parsed
    return json.loads(response.text)


def _parse_pcm_params(mime_type):
    """Pull (rate, channels, sample_width_bytes) from a PCM mime type such as
    'audio/L16;codec=pcm;rate=24000' or 'audio/l16; rate=24000; channels=1'."""
    rate, channels, sample_width = 24000, 1, 2
    if mime_type:
        m = re.search(r"rate=(\d+)", mime_type)
        if m:
            rate = int(m.group(1))
        m = re.search(r"channels=(\d+)", mime_type)
        if m:
            channels = int(m.group(1))
        m = re.search(r"[lL](\d+)", mime_type)  # L16 -> 16-bit -> 2 bytes
        if m:
            sample_width = max(1, int(m.group(1)) // 8)
    return rate, channels, sample_width


@functools.lru_cache(maxsize=1)
def _load_pronunciations():
    """Load the name->respelling lexicon (cached). Returns {} if absent/invalid."""
    if not os.path.exists(PRONUNCIATION_FILE):
        return {}
    try:
        with open(PRONUNCIATION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if not str(k).startswith("_")}


def load_pronunciations():
    """Public accessor for the current pronunciation lexicon (name -> respelling)."""
    return _load_pronunciations()


def apply_pronunciations(text, lexicon=None):
    """Replace lexicon names in the spoken text with their phonetic respelling.

    Longest names first (so multi-word names win), matched on word boundaries so
    a short name isn't found inside a longer one.
    """
    lex = _load_pronunciations() if lexicon is None else lexicon
    if not lex or not text:
        return text
    keys = sorted(lex, key=len, reverse=True)
    pattern = re.compile(
        "|".join(rf"(?<!\w){re.escape(k)}(?!\w)" for k in keys)
    )
    return pattern.sub(lambda m: lex[m.group(0)], text)


def synthesize_speech(text, client=None):
    """Synthesize narration audio for a piece of text via Gemini TTS.

    Returns a dict: {data: raw PCM bytes, rate, channels, sample_width} — ready
    to be written to a WAV container by the caller.
    """
    client = client or get_client()
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=TTS_VOICE)
            )
        ),
    )
    spoken = apply_pronunciations(text)
    prompt = f"{TTS_STYLE}\n\n{spoken}" if TTS_STYLE else spoken

    response = _generate_with_retry(client, TTS_MODEL, prompt, config)
    inline = response.candidates[0].content.parts[0].inline_data
    rate, channels, sample_width = _parse_pcm_params(inline.mime_type)
    return {
        "data": inline.data,
        "rate": rate,
        "channels": channels,
        "sample_width": sample_width,
    }


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
