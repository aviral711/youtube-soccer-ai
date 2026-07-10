# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A data pipeline that ingests completed soccer matches from the (unofficial) FotMob API into a PostgreSQL database, then generates match summaries intended to feed an AI YouTube narration workflow. There is no web server or UI — everything is run as one-off scripts.

## Commands

Use the project virtualenv (`.venv`). All scripts are run from the repo root.

```bash
# Load all completed, not-yet-stored matches for a date (defaults to YESTERDAY, US/Central).
# Accepts YYYYMMDD or YYYY-MM-DD.
python daily_match_loader.py            # yesterday
python daily_match_loader.py 2026-06-27 # specific date

# Fetch + load a single match by FotMob match ID (edit the ID in __main__)
python fetch_matches.py

# Build the summary object for a single match (edit MATCH_ID in main())
python generate_summary.py
```

There is no test suite, linter, or build step configured. `temp_test.py` is a scratch/exploration file, not a test.

## Data flow

The pipeline is a linear chain — read it in this order to understand the whole thing:

1. **`daily_match_loader.py`** — entry point. Fetches the daily match list, then for each match calls `should_load_match` (loads only if `finished` AND not already in DB via `match_exists`). Idempotent: re-running a date skips matches already stored. Wraps each match in try/except so one failure doesn't abort the run.
2. **`fetch_matches.py`** — for one match ID: fetches match detail JSON, writes a raw copy to `match_jsons/`, then extracts three shapes from the deeply-nested API response:
   - `extract_match_data` → one match row (teams, score, winner, competition, country).
   - `extract_stat_records` → per-stat home/away values (defensively coded — returns `[]` if the nested `content.stats.Periods.All.stats` path is missing).
   - `extract_event_records` → goals, cards, substitutions, added time, with shotmap/xG fields when present.
3. **`load_match.py`** — inserts those three shapes into `soccer.matches`, `soccer.match_events`, `soccer.match_stats` in a single transaction (`engine.begin()`). Matches and events use `ON CONFLICT DO NOTHING`; **stats have no conflict guard**, so re-inserting the same match's stats will duplicate rows (the loader normally prevents this via the `match_exists` check upstream, not the DB).
4. **`generate_summary.py`** — reads a stored match back out (`get_match`/`get_events`/`get_stats`) and assembles a `summary` dict with empty `timeline`/`storyline` placeholders. This is the draft/WIP stage of the project; `save_summary` is currently a no-op pass-through.

`common_utils.py` holds all FotMob URL builders, the HTTP fetch, JSON file writer, and `get_country_name` (converts FotMob's FIFA-style country codes to names, with a `SPECIAL_CODES` override for cases like `ENG`/`SCO`/`INT` that don't follow ISO 3166-1 alpha-3).

## Database

- Connection is hardcoded in `database.py`: `postgresql+psycopg2://postgres:postgres@localhost:5432/soccer_ai`. A local Postgres with a `soccer` schema and the `matches`, `match_events`, `match_stats` tables must already exist — **there are no migrations or schema DDL in this repo**; the tables are managed externally. Column lists in `load_match.py`'s INSERT statements are the de-facto schema reference.
- `match_id` is stored/compared as `varchar` (see the `CAST(:match_id AS varchar)` in `match_exists`).
- Comments in `load_match.py` mark planned-but-unimplemented columns (`season`, `stage`, `venue_name`).

## Gotchas

- **`requirements.txt` is incomplete and UTF-16 encoded.** `common_utils.py` imports `pycountry` and `country_converter` (`coco`), neither of which is listed. Install them manually if `get_country_name` fails.
- The FotMob API is unofficial and unauthenticated; the daily-matches URL is pinned to `timezone=America/Chicago` and `ccode3=USA`, which affects which matches appear and the "yesterday" default in `normalize_match_date`.
- Logging goes to `logs/pipeline.log` (INFO level), configured at import time in `daily_match_loader.py`.
- Every processed match's raw API JSON is persisted to `match_jsons/` (~350 files tracked in git) — useful for offline inspection of the source structure that the `extract_*` functions parse.
