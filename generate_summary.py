# generate_summary.py
#
# Reads ONE match from Postgres (soccer.matches / match_events / match_stats)
# and writes two AI-ready JSON files to summaries/:
#
#   match_<id>_summary.json    - full: match meta, all stats, full timeline, storyline
#   match_<id>_highlights.json - condensed: goals / red cards / missed penalties
#                                and the handful of stats useful for a 15-30s recap
#
# This module does NOT generate AI text. Every "description" string is a
# deterministic template assembled from database columns; the downstream AI
# tool turns this JSON into a narration script.

import os
import json
import argparse

from sqlalchemy import text
from database import engine

OUTPUT_DIR = "summaries"

# Event types kept in the full timeline (Half / AddedTime / Comment are dropped).
TIMELINE_TYPES = {
    "Goal", "Card", "Substitution", "MissedPenalty", "VAR", "PenaltyShootout",
}

# Stats most relevant to a short recap, in display order. Keys are FotMob's
# stat_key values (note the "BallPossesion" spelling comes from the source API).
HIGHLIGHT_STAT_KEYS = [
    "BallPossesion",
    "expected_goals",
    "total_shots",
    "ShotsOnTarget",
    "big_chance",
    "corners",
]


# --------------------------------------------------------------------------- #
# Database reads
# --------------------------------------------------------------------------- #
def get_match(match_id):
    """Return the match row as a dict, or None if not found.

    NB: soccer.matches.match_id is varchar while match_events/match_stats.match_id
    are bigint, so each query casts :match_id to the column's own type. This lets
    callers pass match_id as a plain string (e.g. straight from argparse).
    """
    query = text("""
        SELECT *
        FROM soccer.matches
        WHERE match_id = CAST(:match_id AS varchar)
    """)
    with engine.connect() as conn:
        row = conn.execute(query, {"match_id": match_id}).mappings().first()
    return dict(row) if row else None


def get_events(match_id):
    """Return all events for the match, ordered chronologically."""
    query = text("""
        SELECT *
        FROM soccer.match_events
        WHERE match_id = CAST(:match_id AS bigint)
        ORDER BY minute, minute_added
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {"match_id": match_id}).mappings().all()
    return [dict(r) for r in rows]


def get_stats(match_id):
    """Return match stats as a list of records (keeps stat_key for filtering)."""
    query = text("""
        SELECT stat_key, stat_title, home_value, away_value
        FROM soccer.match_stats
        WHERE match_id = CAST(:match_id AS bigint)
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {"match_id": match_id}).mappings().all()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Small formatting helpers
# --------------------------------------------------------------------------- #
def _clock(ev):
    """Return a match-clock label like "26'" or "45+2'" (empty if no minute)."""
    minute = ev.get("minute")
    if minute is None:
        return ""
    added = ev.get("minute_added")
    return f"{minute}+{added}'" if added else f"{minute}'"


def _team_name(match, ev):
    """Resolve the event's team name from its HOME/AWAY side."""
    return match.get("home_team") if ev.get("team_side") == "HOME" else match.get("away_team")


def _actor(match, ev):
    """"Player (Team)" for the event, degrading to just the team when the
    player name is missing (some source events store no player)."""
    team = _team_name(match, ev)
    player = ev.get("player_name")
    return f"{player} ({team})" if player else str(team)


def _score_after(ev):
    """Return the "home-away" score after the event, falling back to before."""
    h, a = ev.get("home_score_after"), ev.get("away_score_after")
    if h is None or a is None:
        h, a = ev.get("home_score_before"), ev.get("away_score_before")
    if h is None or a is None:
        return ""
    return f"{h}-{a}"


def _split_score(display):
    """Parse "1-0" into (1, 0); return (None, None) if unparseable."""
    if not display or "-" not in display:
        return None, None
    try:
        h, a = display.split("-", 1)
        return int(h), int(a)
    except ValueError:
        return None, None


def _outcome(match):
    """Classify the result as home_win / away_win / draw / unknown."""
    hs, as_ = match.get("home_score"), match.get("away_score")
    if hs is None or as_ is None:
        return "unknown"
    if hs > as_:
        return "home_win"
    if as_ > hs:
        return "away_win"
    return "draw"


# --------------------------------------------------------------------------- #
# Deterministic event descriptions (one branch per event_type)
# --------------------------------------------------------------------------- #
def describe_event(match, ev):
    """Build a factual one-line description for any event type.

    Every branch reads only from DB columns; unknown/future types fall back to
    a generic "<clock> <type>" string so the pipeline never breaks.
    """
    clock = _clock(ev)
    prefix = f"{clock} " if clock else ""
    etype = ev.get("event_type")
    team = _team_name(match, ev)
    player = ev.get("player_name")

    if etype == "Goal":
        score = _score_after(ev)
        tail = f" {score}" if score else ""
        if ev.get("is_own_goal"):
            return f"{prefix}Own goal — {_actor(match, ev)}.{tail}"
        qualifier = " (penalty)" if ev.get("situation") == "Penalty" else ""
        assist = ev.get("assist_player_name")
        assist_str = f", assist {assist}" if assist else ""
        return f"{prefix}Goal{qualifier} — {_actor(match, ev)}{assist_str}.{tail}"

    if etype == "Card":
        label = {
            "Yellow": "Yellow card",
            "Red": "Red card",
            "YellowRed": "Second yellow → sent off",
        }.get(ev.get("card_type"), f"{ev.get('card_type')} card")
        return f"{prefix}{label} — {_actor(match, ev)}"

    if etype == "Substitution":
        return (
            f"{prefix}Substitution ({team}) — "
            f"{ev.get('player_in_name')} on for {ev.get('player_out_name')}"
        )

    if etype == "MissedPenalty":
        return f"{prefix}Penalty missed — {_actor(match, ev)}"

    if etype == "VAR":
        return f"{prefix}VAR check — {ev.get('event_description') or 'review'}"

    if etype == "PenaltyShootout":
        detail = ev.get("event_description") or f"{player} ({team})"
        return f"{prefix}Penalty shootout — {detail}"

    if etype == "AddedTime":
        added = ev.get("minutes_added")
        return f"{prefix}Added time: +{added} min" if added else f"{prefix}Added time"

    if etype == "Half":
        return f"{prefix}Half".strip()

    if etype == "Comment":
        return f"{prefix}{ev.get('event_description') or 'Comment'}"

    # Fallback for any event type not covered above.
    return f"{prefix}{etype}".strip()


# --------------------------------------------------------------------------- #
# Timeline, storyline, and output assembly
# --------------------------------------------------------------------------- #
def build_timeline(match, events):
    """Return the chronological list of meaningful events, each enriched with
    structured fields plus a deterministic description string."""
    timeline = []
    for ev in events:
        if ev.get("event_type") not in TIMELINE_TYPES:
            continue
        timeline.append({
            "clock": _clock(ev),
            "minute": ev.get("minute"),
            "minute_added": ev.get("minute_added"),
            "type": ev.get("event_type"),
            "team_side": ev.get("team_side"),
            "team": _team_name(match, ev),
            "player": ev.get("player_name"),
            "assist": ev.get("assist_player_name"),
            "card_type": ev.get("card_type"),
            "player_in": ev.get("player_in_name"),
            "player_out": ev.get("player_out_name"),
            "is_own_goal": ev.get("is_own_goal"),
            "situation": ev.get("situation"),
            "expected_goals": ev.get("expected_goals"),
            "score_after": _score_after(ev),
            "description": describe_event(match, ev),
        })
    return timeline


def _condense(entry):
    """Trim a timeline entry down to the fields a recap needs."""
    return {
        "clock": entry["clock"],
        "type": entry["type"],
        "team": entry["team"],
        "player": entry["player"],
        "card_type": entry["card_type"],
        "score_after": entry["score_after"],
        "description": entry["description"],
    }


def build_storyline(match, timeline):
    """Derive narrative beats (result, goal progression, lead changes, tags)
    from the timeline. Purely mechanical — a scaffold for the AI to narrate."""
    outcome = _outcome(match)
    hs, as_ = match.get("home_score"), match.get("away_score")

    goals = [e for e in timeline if e["type"] == "Goal"]
    reds = [
        e for e in timeline
        if e["type"] == "Card" and e.get("card_type") in ("Red", "YellowRed")
    ]

    winner_side = {"home_win": "home", "away_win": "away"}.get(outcome)

    # Walk the goals to track lead changes, who ever trailed, and when the
    # eventual winner took their final lead (for the late-winner tag).
    lead_changes = 0
    last_ahead = None             # last team strictly in front ("home"/"away")
    ever_trailed = {"home": False, "away": False}
    winner_last_ahead_minute = None
    for g in goals:
        h, a = _split_score(g["score_after"])
        if h is None:
            continue
        if h > a:
            ahead, trailing = "home", "away"
        elif a > h:
            ahead, trailing = "away", "home"
        else:
            ahead, trailing = None, None       # level

        if trailing:
            ever_trailed[trailing] = True
        if ahead:
            # A true lead change only when the OTHER team had been in front.
            if last_ahead is not None and last_ahead != ahead:
                lead_changes += 1
            last_ahead = ahead
            if ahead == winner_side:
                winner_last_ahead_minute = g.get("minute")

    tags = []
    if winner_side and ever_trailed[winner_side]:
        tags.append("comeback")
    if hs is not None and as_ is not None:
        total = hs + as_
        if total == 0:
            tags.append("goalless_draw")
        elif min(hs, as_) == 0 and outcome != "draw":
            tags.append("clean_sheet")
        if total >= 4:
            tags.append("high_scoring")
    if lead_changes >= 2:
        tags.append("lead_swings")
    # Winner sealed it (took their final lead) at 80'+.
    if winner_last_ahead_minute is not None and winner_last_ahead_minute >= 80:
        tags.append("late_winner")
    if reds:
        tags.append("red_card")
    if any(e["type"] == "PenaltyShootout" for e in timeline):
        tags.append("shootout")

    goal_beats = [_condense(g) for g in goals]
    return {
        "outcome": outcome,
        "winner": match.get("winner"),
        "final_score": f"{hs}-{as_}" if hs is not None and as_ is not None else None,
        "opening_goal": goal_beats[0] if goal_beats else None,
        "goals": goal_beats,
        "lead_changes": lead_changes,
        "red_cards": [_condense(r) for r in reds],
        "tags": tags,
    }


def build_match_summary(match, events, stats):
    """Assemble the full AI-ready summary object."""
    outcome = _outcome(match)
    hs, as_ = match.get("home_score"), match.get("away_score")
    timeline = build_timeline(match, events)

    return {
        "match": match,
        "final_score": {
            "home": hs,
            "away": as_,
            "display": f"{hs}-{as_}" if hs is not None and as_ is not None else None,
            "winner": match.get("winner"),
            "outcome": outcome,
        },
        "stats": [
            {
                "stat_key": s.get("stat_key"),
                "stat_title": s.get("stat_title"),
                "home": s.get("home_value"),
                "away": s.get("away_value"),
            }
            for s in stats
        ],
        "timeline": timeline,
        "storyline": build_storyline(match, timeline),
    }


def build_highlights(match, summary):
    """Assemble the condensed recap object: goals, red cards, missed penalties,
    and a short list of the most relevant stats."""
    key_events = []
    for e in summary["timeline"]:
        if e["type"] in ("Goal", "MissedPenalty"):
            key_events.append(_condense(e))
        elif e["type"] == "Card" and e["card_type"] in ("Red", "YellowRed"):
            key_events.append(_condense(e))

    stats_by_key = {s["stat_key"]: s for s in summary["stats"]}
    key_stats = []
    for key in HIGHLIGHT_STAT_KEYS:
        s = stats_by_key.get(key)
        if s:
            key_stats.append({
                "stat_title": s["stat_title"],
                "home": s["home"],
                "away": s["away"],
            })

    return {
        "match": {
            "match_id": match.get("match_id"),
            "competition": match.get("competition"),
            "match_date": match.get("match_date"),
            "home_team": match.get("home_team"),
            "away_team": match.get("away_team"),
        },
        "final_score": summary["final_score"],
        "key_events": key_events,
        "key_stats": key_stats,
    }


def write_json(data, path):
    """Write an object to JSON. default=str handles date/Decimal; keep unicode
    (player names with accents) readable rather than escaped."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


# --------------------------------------------------------------------------- #
# Orchestration / CLI
# --------------------------------------------------------------------------- #
def generate(match_id):
    """Read one match from the DB and write its summary + highlights JSON."""
    match = get_match(match_id)
    if not match:
        print(f"No match found for match_id={match_id}")
        return None

    events = get_events(match_id)
    stats = get_stats(match_id)

    summary = build_match_summary(match, events, stats)
    highlights = build_highlights(match, summary)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    summary_path = os.path.join(OUTPUT_DIR, f"match_{match_id}_summary.json")
    highlights_path = os.path.join(OUTPUT_DIR, f"match_{match_id}_highlights.json")
    write_json(summary, summary_path)
    write_json(highlights, highlights_path)

    print(
        f"Match {match_id}: {match.get('home_team')} vs {match.get('away_team')} | "
        f"{len(summary['timeline'])} timeline events, "
        f"{len(highlights['key_events'])} highlights"
    )
    print(f"Wrote {summary_path}")
    print(f"Wrote {highlights_path}")
    return summary, highlights


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate AI-ready summary + highlights JSON for one match."
    )
    parser.add_argument(
        "match_id",
        help="Match ID to summarize, as stored in soccer.matches.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    generate(args.match_id)
