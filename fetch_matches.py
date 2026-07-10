# fetch_matches.py

import json

from load_match import load_match
from common_utils import (
    build_match_details_url,
    build_match_json_filename,
    fetch_from_api,
    save_json_to_file,
    get_country_name
)


def extract_match_data(data_details):
    """Extract match-level fields from the API response."""
    return {
        "match_id": data_details["general"]["matchId"],
        "country_code": data_details["general"]["countryCode"] if data_details["general"].get("countryCode") else None,
        "country_name": get_country_name(data_details["general"]["countryCode"]) if data_details["general"].get("countryCode") else None,
        "competition": data_details["general"]["leagueName"],
        "match_date": data_details["general"]["matchTimeUTCDate"],
        "home_team": data_details["general"]["homeTeam"]["name"],
        "away_team": data_details["general"]["awayTeam"]["name"],
        "home_score": data_details["header"]["teams"][0]["score"],
        "away_score": data_details["header"]["teams"][1]["score"],
        "winner": (
            data_details["general"]["homeTeam"]["name"]
            if data_details["header"]["teams"][0]["score"] >
               data_details["header"]["teams"][1]["score"]
            else data_details["general"]["awayTeam"]["name"]
        )
    }


def extract_stat_records(match_id, data_details):
    """Extract statistics records from the API response."""
    stat_records = []
    seen_stats = set()

    # Safely navigate nested JSON; return empty list if structure isn't present
    try:
        stat_groups = data_details["content"]["stats"]["Periods"]["All"]["stats"]
    except (KeyError, TypeError):
        return stat_records

    if not isinstance(stat_groups, list):
        return stat_records

    for group in stat_groups:
        if not isinstance(group, dict):
            continue

        group_stats = group.get("stats")
        if not isinstance(group_stats, list):
            continue

        for stat in group_stats:
            if not isinstance(stat, dict):
                continue

            if stat.get("type") == "title":
                continue

            stat_key = stat.get("key")
            if not stat_key or stat_key in seen_stats:
                continue

            seen_stats.add(stat_key)

            # Safely extract numeric/string values from stat['stats']
            raw_values = stat.get("stats")
            home_value = None
            away_value = None
            if isinstance(raw_values, (list, tuple)):
                if len(raw_values) > 0:
                    home_value = raw_values[0]
                if len(raw_values) > 1:
                    away_value = raw_values[1]

            stat_records.append({
                "match_id": match_id,
                "stat_key": stat_key,
                "stat_title": stat.get("title"),
                "home_value": str(home_value) if home_value is not None else None,
                "away_value": str(away_value) if away_value is not None else None,
            })

    return stat_records


def extract_event_records(match_id, data_details):
    """Extract event records from the API response."""
    event_list = data_details["content"]["matchFacts"]["events"]["events"]
    event_records = []
    seen_event_ids = set()

    for index, event in enumerate(event_list, start=1):
        card_type = event.get("card") if event.get("type") == "Card" else None
        minutes_added = event.get("minutesAddedInput") if event.get("type") == "AddedTime" else None

        raw_event_id = event.get("eventId")
        if raw_event_id in (None, 0) or raw_event_id in seen_event_ids:
            event_id = int(f"{match_id}{index:03d}")
        else:
            event_id = int(raw_event_id)
            seen_event_ids.add(event_id)

        player_out_id = None
        player_out_name = None
        player_in_id = None
        player_in_name = None

        if event.get("type") == "Substitution":
            swap = event.get("swap", [])
            if len(swap) >= 2:
                player_out_id = int(swap[0]["id"]) if swap[0].get("id") else None
                player_out_name = swap[0].get("name")
                player_in_id = int(swap[1]["id"]) if swap[1].get("id") else None
                player_in_name = swap[1].get("name")

        event_records.append({
            "event_id": event_id,
            "match_id": match_id,
            "minute": event.get("time"),
            "minute_added": event.get("overloadTime"),
            "event_type": event.get("type"),
            "player_id": event.get("playerId"),
            "player_name": event.get("fullName"),
            "team_side": "HOME" if event.get("isHome") else "AWAY",
            "home_score_before": event.get("homeScore"),
            "away_score_before": event.get("awayScore"),
            "home_score_after": event.get("newScore")[0] if event.get("newScore") else None,
            "away_score_after": event.get("newScore")[1] if event.get("newScore") else None,
            "assist_player_id": event.get("assistPlayerId"),
            "assist_player_name": event.get("assistInput"),
            "is_own_goal": event.get("ownGoal") if event.get("ownGoal") is not None else False,
            "shot_type": event.get("shotmapEvent", {}).get("shotType") if event.get("shotmapEvent") else None,
            "situation": event.get("shotmapEvent", {}).get("situation") if event.get("shotmapEvent") else None,
            "period": event.get("shotmapEvent", {}).get("period") if event.get("shotmapEvent") else None,
            "expected_goals": event.get("shotmapEvent", {}).get("expectedGoals") if event.get("shotmapEvent") else None,
            "card_type": card_type,
            "player_out_id": player_out_id,
            "player_out_name": player_out_name,
            "player_in_id": player_in_id,
            "player_in_name": player_in_name,
            "minutes_added": minutes_added,
            "event_description": event.get("assistStr")
        })

    return event_records


def fetch_match_details(match_id):
    """Fetch match details and load them into the database."""
    url_details = build_match_details_url(match_id)
    data_details = fetch_from_api(url_details)

    match_data = extract_match_data(data_details)
    filename = build_match_json_filename(
        match_data["match_id"],
        match_data["home_team"],
        match_data["away_team"]
    )
    json_path = f"match_jsons/{filename}"
    save_json_to_file(data_details, json_path)

    stat_records = extract_stat_records(match_data["match_id"], data_details)
    event_records = extract_event_records(match_data["match_id"], data_details)

    load_match(match_data, event_records, stat_records)

    return {
        "match_data": match_data,
        "stat_records": stat_records,
        "event_records": event_records
    }


if __name__ == "__main__":
    fetch_match_details("1000007610")
