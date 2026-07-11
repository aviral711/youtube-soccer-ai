# generate_voiceover.py
#
# Pipeline stage 3: turn each match's narration script into a voiceover audio
# file using Gemini TTS.
#
# Standalone and idempotent (Pattern B) with filesystem tracking:
#   in  : scripts/match_<id>_script.json   (the "voiceover" field, from Gemini)
#   out : audio/match_<id>.wav             (24kHz 16-bit mono WAV)
# A match "needs audio" when its script exists but its .wav does not, so this
# can be re-run freely and only fills the gaps.
#
# Invocation (mirrors generate_script.py):
#   python generate_voiceover.py                 # all pending (default)
#   python generate_voiceover.py 4667775         # one match
#   python generate_voiceover.py --date 2026-07-10
#   python generate_voiceover.py --all --force   # re-synthesize everything
# Extra knobs: --limit N, --sleep S (delay between API calls).

import os
import re
import json
import time
import wave
import argparse

from gemini_config import get_client, synthesize_speech
import generate_script  # reuse script-file discovery + the --date summary filter

AUDIO_DIR = "audio"
SCRIPT_RE = re.compile(r"^match_(.+)_script\.json$")


# --------------------------------------------------------------------------- #
# Filesystem tracking / work discovery
# --------------------------------------------------------------------------- #
def audio_path(match_id):
    return os.path.join(AUDIO_DIR, f"match_{match_id}.wav")


def all_script_ids():
    """Every match_id that has a script file."""
    script_dir = generate_script.SCRIPT_DIR
    if not os.path.isdir(script_dir):
        return []
    ids = []
    for name in os.listdir(script_dir):
        m = SCRIPT_RE.match(name)
        if m:
            ids.append(m.group(1))
    return ids


def pending_ids():
    """Match ids that have a script but not yet an audio file."""
    return [mid for mid in all_script_ids() if not os.path.exists(audio_path(mid))]


def ids_for_date(date_str):
    """Match ids for a given date (by stored match_date) that have a script."""
    have_script = set(all_script_ids())
    return [mid for mid in generate_script.ids_for_date(date_str) if mid in have_script]


def load_voiceover(match_id):
    """Read the 'voiceover' narration text from a match's script JSON."""
    with open(generate_script.script_path(match_id), "r", encoding="utf-8") as f:
        return json.load(f).get("voiceover")


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def write_wav(path, audio):
    """Wrap raw PCM (from synthesize_speech) into a WAV container."""
    os.makedirs(AUDIO_DIR, exist_ok=True)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(audio["channels"])
        wf.setsampwidth(audio["sample_width"])
        wf.setframerate(audio["rate"])
        wf.writeframes(audio["data"])


def generate_for_match(match_id, client=None, force=False):
    """Synthesize and write the voiceover for one match.

    Returns "generated" or "skipped" (no script, empty voiceover, or audio
    already present and not forced).
    """
    if not os.path.exists(generate_script.script_path(match_id)):
        print(f"[skip] {match_id}: no script")
        return "skipped"

    out_path = audio_path(match_id)
    if os.path.exists(out_path) and not force:
        print(f"[skip] {match_id}: audio already exists")
        return "skipped"

    voiceover = load_voiceover(match_id)
    if not voiceover:
        print(f"[skip] {match_id}: script has no voiceover text")
        return "skipped"

    client = client or get_client()
    audio = synthesize_speech(voiceover, client=client)
    write_wav(out_path, audio)

    seconds = len(audio["data"]) / (
        audio["rate"] * audio["channels"] * audio["sample_width"]
    )
    print(f"[ok]   {match_id}: wrote {out_path} ({seconds:.1f}s)")
    return "generated"


def run(match_ids, force=False, sleep=0.0):
    """Synthesize voiceovers for a list of match ids, one Gemini client reused.

    Each match is isolated so one failure can't abort the batch.
    """
    if not match_ids:
        print("Nothing to do.")
        return {"generated": 0, "skipped": 0, "failed": 0}

    client = get_client()  # fail fast if the API key is missing
    stats = {"generated": 0, "skipped": 0, "failed": 0}

    for i, match_id in enumerate(match_ids):
        try:
            status = generate_for_match(match_id, client=client, force=force)
            stats[status] += 1
        except Exception as exc:
            stats["failed"] += 1
            print(f"[fail] {match_id}: {exc}")

        if sleep and i < len(match_ids) - 1:
            time.sleep(sleep)

    print(
        f"Done. generated={stats['generated']} "
        f"skipped={stats['skipped']} failed={stats['failed']}"
    )
    return stats


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def resolve_targets(args):
    """Decide which match ids to process from the CLI selectors."""
    if args.match_id:
        return [args.match_id]
    if args.date:
        return sorted(ids_for_date(args.date))
    if args.all:
        return sorted(all_script_ids())
    # Default (and --pending): only scripts without audio.
    return sorted(pending_ids())


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate voiceover audio from match scripts (Gemini TTS)."
    )
    parser.add_argument(
        "match_id", nargs="?", default=None,
        help="A single match id to process. Omit to use a selector below.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--pending", action="store_true",
        help="Process every script that has no audio yet (default).",
    )
    group.add_argument(
        "--date", help="Process matches whose match_date is this day (YYYY-MM-DD).",
    )
    group.add_argument(
        "--all", action="store_true",
        help="Process every script (skips ones with audio unless --force).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-synthesize even if an audio file already exists.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Cap the number of matches processed this run.",
    )
    parser.add_argument(
        "--sleep", type=float, default=0.0,
        help="Seconds to wait between API calls (for rate limiting).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    targets = resolve_targets(args)
    if args.limit is not None:
        targets = targets[:args.limit]
    print(f"Selected {len(targets)} match(es).")
    run(targets, force=args.force, sleep=args.sleep)


if __name__ == "__main__":
    main()
