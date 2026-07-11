# generate_script.py
#
# Pipeline stage 2: turn match summaries into YouTube Shorts scripts via Gemini.
#
# Standalone and idempotent (Pattern B) with filesystem tracking:
#   in  : summaries/match_<id>_summary.json   (from generate_summary.py)
#   out : scripts/match_<id>_script.json      (Gemini output)
# A match "needs a script" when its summary exists but its script does not, so
# this can be re-run freely and only fills the gaps.
#
# Invocation (see also the pipeline orchestrator):
#   python generate_script.py                 # process all pending (default)
#   python generate_script.py --pending       # same, explicit
#   python generate_script.py 4667775         # one match
#   python generate_script.py --date 2026-07-10
#   python generate_script.py --all --force   # regenerate every script
# Extra knobs: --limit N (cap this run), --sleep S (delay between API calls).

import os
import re
import json
import time
import argparse

from ai_prompt import load_match_summary
from gemini_config import get_client, generate_script as generate_script_from_summary

SUMMARY_DIR = "summaries"
SCRIPT_DIR = "scripts"
SUMMARY_RE = re.compile(r"^match_(.+)_summary\.json$")


# --------------------------------------------------------------------------- #
# Filesystem tracking / work discovery
# --------------------------------------------------------------------------- #
def summary_path(match_id):
    return os.path.join(SUMMARY_DIR, f"match_{match_id}_summary.json")


def script_path(match_id):
    return os.path.join(SCRIPT_DIR, f"match_{match_id}_script.json")


def all_summary_ids():
    """Every match_id that has a summary file."""
    if not os.path.isdir(SUMMARY_DIR):
        return []
    ids = []
    for name in os.listdir(SUMMARY_DIR):
        m = SUMMARY_RE.match(name)
        if m:
            ids.append(m.group(1))
    return ids


def pending_ids():
    """Match ids that have a summary but not yet a script."""
    return [mid for mid in all_summary_ids() if not os.path.exists(script_path(mid))]


def _norm_date(s):
    """Normalize YYYYMMDD or YYYY-MM-DD to a 'YYYY-MM-DD' prefix."""
    s = s.strip()
    if "-" in s:
        return s[:10]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def ids_for_date(date_str):
    """Match ids whose stored match_date falls on the given date."""
    prefix = _norm_date(date_str)
    ids = []
    for mid in all_summary_ids():
        try:
            summary = load_match_summary(summary_path(mid))
        except (OSError, json.JSONDecodeError):
            continue
        match_date = str(summary.get("match", {}).get("match_date") or "")
        if match_date.startswith(prefix):
            ids.append(mid)
    return ids


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def generate_for_match(match_id, client=None, force=False):
    """Generate and write the script for one match.

    Returns a status: "generated", "skipped" (no summary, or script already
    present and not forced).
    """
    sp = summary_path(match_id)
    if not os.path.exists(sp):
        print(f"[skip] {match_id}: no summary at {sp}")
        return "skipped"

    out_path = script_path(match_id)
    if os.path.exists(out_path) and not force:
        print(f"[skip] {match_id}: script already exists")
        return "skipped"

    summary = load_match_summary(sp)
    client = client or get_client()
    script = generate_script_from_summary(summary, client=client)

    os.makedirs(SCRIPT_DIR, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    print(f"[ok]   {match_id}: wrote {out_path}")
    return "generated"


def run(match_ids, force=False, sleep=0.0):
    """Generate scripts for a list of match ids, one Gemini client reused.

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
        return sorted(all_summary_ids())
    # Default (and --pending): only summaries without a script.
    return sorted(pending_ids())


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate YouTube Shorts scripts from match summaries (Gemini)."
    )
    parser.add_argument(
        "match_id", nargs="?", default=None,
        help="A single match id to process. Omit to use a selector below.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--pending", action="store_true",
        help="Process every summary that has no script yet (default).",
    )
    group.add_argument(
        "--date", help="Process matches whose match_date is this day (YYYY-MM-DD).",
    )
    group.add_argument(
        "--all", action="store_true",
        help="Process every summary (skips ones with a script unless --force).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Regenerate even if a script already exists.",
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
