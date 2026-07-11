# update_pronunciations.py
#
# Discovery helper for the TTS pronunciation lexicon (pronunciations.json).
#
# It does NOT auto-edit the active lexicon (correct pronunciation can't be
# auto-verified). Instead it:
#   1. scans structured summaries for player/team names,
#   2. diffs them against names already in pronunciations.json,
#   3. reports the missing ones, frequency-ranked (curate recurring names first),
#   4. optionally (--draft) asks Gemini to PROPOSE respellings, written to a
#      separate review file you approve by ear before merging.
#
# Usage:
#   python update_pronunciations.py                     # ranked worklist to stdout
#   python update_pronunciations.py --min-count 2       # only recurring names
#   python update_pronunciations.py --out todo.json     # also write the worklist
#   python update_pronunciations.py --draft --limit 20  # draft respellings for review
#   python update_pronunciations.py --draft --min-count 3
#
# Nothing here changes pronunciations.json — you copy approved entries in yourself.

import os
import json
import argparse
from collections import Counter

from pydantic import BaseModel

import ai_prompt
import generate_script
import gemini_config

DRAFT_FILE = "pronunciations.draft.json"
DRAFT_CHUNK = 50  # names per Gemini request

# Structured summary fields that hold a person's name.
NAME_FIELDS = ("player", "assist", "player_in", "player_out")


# --------------------------------------------------------------------------- #
# Name discovery
# --------------------------------------------------------------------------- #
def collect_names(match_ids=None):
    """Count player + team names across the summaries for the given match ids
    (all summaries if None)."""
    ids = match_ids if match_ids is not None else generate_script.all_summary_ids()
    counter = Counter()
    for mid in ids:
        try:
            summary = ai_prompt.load_match_summary(generate_script.summary_path(mid))
        except (OSError, json.JSONDecodeError):
            continue
        for event in summary.get("timeline", []):
            for field in NAME_FIELDS:
                value = event.get(field)
                if value:
                    counter[value] += 1
        match = summary.get("match", {})
        for field in ("home_team", "away_team"):
            value = match.get(field)
            if value:
                counter[value] += 1
    return counter


def missing_names(counter, min_count=1):
    """Ranked (name, count) pairs not yet covered by the lexicon, count >= min_count.

    A name counts as covered if applying the lexicon changes it — this catches
    surname keys (e.g. "Güler") already handling a full name ("Arda Güler"),
    matching how the lexicon is actually applied to the spoken text.
    """
    lex = gemini_config.load_pronunciations()
    result = []
    for name, count in counter.most_common():
        if count < min_count:
            continue
        if name in lex or gemini_config.apply_pronunciations(name, lex) != name:
            continue
        result.append((name, count))
    return result


# --------------------------------------------------------------------------- #
# Draft respellings via Gemini (proposals only, never auto-applied)
# --------------------------------------------------------------------------- #
class NamePronunciation(BaseModel):
    name: str
    respelling: str


class DraftResult(BaseModel):
    pronunciations: list[NamePronunciation]


DRAFT_PROMPT = """\
These are association football (soccer) player and team names. For each, give a
phonetic respelling using plain English syllables (hyphenated, with the stressed
syllable capitalized) that an English text-to-speech engine will read close to
the correct native pronunciation. Keep it simple and readable — NOT IPA.

Example: "Söyüncü" -> "soy-OON-joo"

Names:
{names}

Return JSON with a "pronunciations" array containing every name and its respelling.
"""


def draft_respellings(names, client=None):
    """Ask Gemini to propose respellings for a list of names. Returns
    {name: respelling}. Batched to keep requests reasonable."""
    client = client or gemini_config.get_client()
    drafts = {}
    for start in range(0, len(names), DRAFT_CHUNK):
        chunk = names[start:start + DRAFT_CHUNK]
        prompt = DRAFT_PROMPT.format(names="\n".join(f"- {n}" for n in chunk))
        result = gemini_config.generate_json(
            prompt, response_schema=DraftResult, client=client
        )
        for item in result.get("pronunciations", []):
            name, respelling = item.get("name"), item.get("respelling")
            if name and respelling:
                drafts[name] = respelling
        print(f"[draft] {min(start + DRAFT_CHUNK, len(names))}/{len(names)} names")
    return drafts


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args():
    parser = argparse.ArgumentParser(
        description="Report names missing from the TTS pronunciation lexicon; "
                    "optionally draft respellings for review."
    )
    parser.add_argument(
        "--date", help="Only scan matches whose match_date is this day (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--min-count", type=int, default=1,
        help="Only names seen at least this many times (default 1).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Cap the number of names processed.",
    )
    parser.add_argument(
        "--draft", action="store_true",
        help="Ask Gemini to propose respellings, written to a review file.",
    )
    parser.add_argument(
        "--out", help="Write the worklist / draft here (default draft: "
                      f"{DRAFT_FILE}).",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    match_ids = None
    if args.date:
        match_ids = generate_script.ids_for_date(args.date)

    counter = collect_names(match_ids)
    missing = missing_names(counter, min_count=args.min_count)
    if args.limit is not None:
        missing = missing[:args.limit]

    print(f"{len(missing)} name(s) missing from the lexicon "
          f"(min_count={args.min_count}).")
    for name, count in missing:
        print(f"  {count:>3}x  {name}")

    if not missing:
        return

    if args.draft:
        names = [name for name, _ in missing]
        drafts = draft_respellings(names)
        out_path = args.out or DRAFT_FILE
        payload = {
            "_note": "DRAFT respellings for review. Verify by ear, then copy good "
                     "entries into pronunciations.json. Nothing here is applied "
                     "automatically.",
            **drafts,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"Wrote {len(drafts)} draft respelling(s) to {out_path} for review.")
    elif args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({name: count for name, count in missing}, f,
                      ensure_ascii=False, indent=2)
        print(f"Wrote worklist ({len(missing)} names) to {args.out}.")


if __name__ == "__main__":
    main()
