# run_pipeline.py
#
# Orchestrates the daily content pipeline end to end. This is the single entry
# point a scheduler invokes (WSL cron or Windows Task Scheduler), e.g. daily:
#
#   # WSL cron (crontab -e) — 6am, defaults to yesterday's matches:
#   0 6 * * *  cd /path/to/repo && .venv/Scripts/python.exe run_pipeline.py >> logs/cron.out 2>&1
#
#   # Windows Task Scheduler — Action:
#   Program : C:\...\repo\.venv\Scripts\python.exe
#   Args    : run_pipeline.py
#   Start in: C:\...\repo
#
# Stages (each isolated so one failing doesn't abort the whole run):
#   1. ingest+summaries : daily_match_loader — FotMob -> Postgres -> summaries/
#   2. scripts          : generate_script    — summaries/ -> Gemini -> scripts/
#   3. voiceover        : generate_voiceover — scripts/ -> Gemini TTS -> audio/
#
# Every stage is idempotent, so a failed or interrupted run is fixed simply by
# the next run picking up whatever is still outstanding.
#   # A specific date
#   ./.venv/Scripts/python.exe run_pipeline.py 2026-07-10
#
#   # Just catch up on script generation, throttled
#   ./.venv/Scripts/python.exe run_pipeline.py --skip-ingest --sleep 2

import time
import logging
import argparse

# NOTE: importing daily_match_loader configures logging to logs/pipeline.log
# (it calls logging.basicConfig at import), so orchestrator logs land there too.
import daily_match_loader
import generate_script
import generate_voiceover


def announce(message):
    """Log to the pipeline log file and echo to the console."""
    logging.info(message)
    print(message)


def run_stage(name, fn):
    """Run one stage, timing it and isolating failures.

    Returns (ok, result): ok is False if the stage raised.
    """
    announce(f"[pipeline] START stage: {name}")
    start = time.monotonic()
    try:
        result = fn()
        announce(f"[pipeline] DONE  stage: {name} ({time.monotonic() - start:.1f}s)")
        return True, result
    except Exception:
        logging.exception(f"[pipeline] FAILED stage: {name}")
        print(f"[pipeline] FAILED stage: {name} (see logs/pipeline.log)")
        return False, None


def ingest_stage(match_date):
    """Stage 1: load new matches and write their summaries."""
    daily_match_loader.main(match_date)


def scripts_stage(limit=None, sleep=0.0):
    """Stage 2: generate Gemini scripts for every summary lacking one."""
    pending = generate_script.pending_ids()
    targets = pending[:limit] if limit is not None else pending
    announce(
        f"[pipeline] {len(pending)} script(s) pending; processing {len(targets)}"
    )
    return generate_script.run(targets, sleep=sleep)


def voiceover_stage(limit=None, sleep=0.0):
    """Stage 3: synthesize voiceover audio for every script lacking one."""
    pending = generate_voiceover.pending_ids()
    targets = pending[:limit] if limit is not None else pending
    announce(
        f"[pipeline] {len(pending)} voiceover(s) pending; processing {len(targets)}"
    )
    return generate_voiceover.run(targets, sleep=sleep)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the full daily match -> summary -> script pipeline."
    )
    parser.add_argument(
        "date", nargs="?", default=None,
        help="Match date (YYYYMMDD or YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument(
        "--skip-ingest", action="store_true",
        help="Skip stage 1 (don't fetch/load matches); only generate scripts.",
    )
    parser.add_argument(
        "--skip-scripts", action="store_true",
        help="Skip stage 2 (don't call Gemini); only ingest + summarize.",
    )
    parser.add_argument(
        "--skip-voiceover", action="store_true",
        help="Skip stage 3 (don't synthesize audio).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Cap the number of scripts generated this run.",
    )
    parser.add_argument(
        "--sleep", type=float, default=0.0,
        help="Seconds to wait between Gemini calls (rate limiting).",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    announce("#" * 60)
    announce(f"[pipeline] run starting (date={args.date or 'yesterday'})")

    results = {}
    if not args.skip_ingest:
        results["ingest"], _ = run_stage(
            "ingest+summaries", lambda: ingest_stage(args.date)
        )
    else:
        announce("[pipeline] skipping stage: ingest+summaries")

    if not args.skip_scripts:
        results["scripts"], stats = run_stage(
            "scripts", lambda: scripts_stage(limit=args.limit, sleep=args.sleep)
        )
        if stats:
            announce(
                f"[pipeline] scripts: generated={stats['generated']} "
                f"skipped={stats['skipped']} failed={stats['failed']}"
            )
    else:
        announce("[pipeline] skipping stage: scripts")

    if not args.skip_voiceover:
        results["voiceover"], stats = run_stage(
            "voiceover", lambda: voiceover_stage(limit=args.limit, sleep=args.sleep)
        )
        if stats:
            announce(
                f"[pipeline] voiceover: generated={stats['generated']} "
                f"skipped={stats['skipped']} failed={stats['failed']}"
            )
    else:
        announce("[pipeline] skipping stage: voiceover")

    announce(f"[pipeline] run complete ({results})")
    announce("#" * 60)


if __name__ == "__main__":
    main()
