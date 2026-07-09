from sqlalchemy import text
from database import engine

def get_match(match_id):
    query = """
        SELECT *
        FROM soccer.matches
        WHERE match_id = :match_id
    """

    with engine.connect() as conn:
        result = conn.execute(text(query), {"match_id": match_id})
        row = result.mappings().first()

    return row

def get_events(match_id):
    query = """
        SELECT *
        FROM soccer.match_events
        WHERE match_id = :match_id
        ORDER BY minute, minute_added
    """

    with engine.connect() as conn:
        result = conn.execute(text(query), {"match_id": match_id})
        rows = result.mappings().all()

    return rows

def get_stats(match_id):
    query = """
    SELECT stat_title, home_value, away_value
    FROM soccer.match_stats
    WHERE match_id = :match_id
    """

    with engine.connect() as conn:
        result = conn.execute(text(query), {"match_id": match_id})
        rows = result.mappings().all()

    stats = {}
    for row in rows:
        stats[row["stat_title"]] = f"{row['home_value']}-{row['away_value']}"

    return stats

def build_summary(match, events, stats):
    match_obj = {}
    if match:
        for key, value in match.items():
            match_obj[key] = value

    event_objects = []
    for event in events or []:
        event_obj = {}
        for key, value in event.items():
            event_obj[key] = value
        event_objects.append(event_obj)

    stats_objects = []
    for stat_title, score in (stats or {}).items():
        stats_objects.append({
            "stat_title": stat_title,
            "score": score
        })

    summary = {
        "match": match_obj,
        "events": event_objects,
        "stats": stats_objects,
        "timeline": [],
        "storyline": []
    }

    return summary


def save_summary(summary):
    return summary


def main():

    match_id=4667817

    match=get_match(match_id)
    events=get_events(match_id)
    stats=get_stats(match_id)
    summary=build_summary(match,events,stats)

    save_summary(summary)