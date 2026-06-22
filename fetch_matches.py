# fetch_matches.py

import requests
import json
from sqlalchemy import text
from database import engine

MATCH_ID = "4667751"

## Fetch Match details
url_details = (
    f"https://www.fotmob.com/api/data/matchDetails"
    f"?matchId={MATCH_ID}"
)

response_details = requests.get(url_details)

# print(response_details.status_code)

data_details = response_details.json()

with open("sample_match.json", "w", encoding="utf-8") as f:
    json.dump(data_details, f, indent=4)

# print("Match Details JSON saved successfully!")

## Data for Matches table
match_data = {
    "match_id": data_details["general"]["matchId"],
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

# print ("Match_Data: ", match_data);

## Data for Match Stats table
stat_records = []
seen_stats = set()

stat_groups = data_details["content"]["stats"]["Periods"]["All"]["stats"]

for group in stat_groups:

    if isinstance(group.get("stats"), list):

        for stat in group["stats"]:
            if stat.get("type") == "title":
                continue
            
            stat_key = stat.get("key")

            if stat_key in seen_stats:
                continue

            seen_stats.add(stat_key)

            record = {
                "match_id": match_data["match_id"],
                "stat_key": stat_key,
                "stat_title": stat.get("title"),
                "home_value": str(stat["stats"][0]),
                "away_value": str(stat["stats"][1])
            }

            stat_records.append(record)

# print ("Match_Stats: ", stat_records[0]);

## Data for Match Events table
event_list = data_details["content"]["matchFacts"]["events"]["events"]

event_records = []

for event in event_list:
    ## Initialize variables for optional fields
    card_type = None
    player_out_id = None
    player_out_name = None
    player_in_id = None
    player_in_name = None
    minutes_added = None

    ## Extract card type for Card events
    if event.get("type") == "Card":
        card_type = event.get("card")
    
    ## Extract minutes added for Added Time events
    if event.get("type") == "AddedTime":
        minutes_added = event.get("minutesAddedInput")

    ## Extract player details for Substitution events
    if event.get("type") == "Substitution":

        swap = event.get("swap", [])

        if len(swap) >= 2:

            player_out_id = (
                int(swap[0]["id"])
                if swap[0].get("id")
                else None
            )

            player_out_name = swap[0].get("name")

            player_in_id = (
                int(swap[1]["id"])
                if swap[1].get("id")
                else None
            )

            player_in_name = swap[1].get("name")

    ## Create event record with all available details
    record = {
        "event_id": event.get("eventId"),
        "match_id": match_data["match_id"],
        "minute": event.get("time"),
        "minute_added": event.get("overloadTime"),
        "event_type": event.get("type"),
        "player_id": event.get("playerId"),
        "player_name": event.get("fullName"),
        "team_side": "HOME" if event.get("isHome") else "AWAY",
        "home_score_before": event.get("homeScore"),
        "away_score_before": event.get("awayScore"),
        "home_score_after": (
            event.get("newScore")[0]
            if event.get("newScore")
            else None
        ),
        "away_score_after": (
            event.get("newScore")[1]
            if event.get("newScore")
            else None
        ),
        "assist_player_id": event.get("assistPlayerId"),
        "assist_player_name": event.get("assistInput"),
        "is_own_goal": (
            event.get("ownGoal")
            if event.get("ownGoal") is not None
            else False
        ),
        "shot_type": (
        event.get("shotmapEvent", {})
             .get("shotType")
        ),
        "situation": (
            event.get("shotmapEvent", {})
                .get("situation")
        ),
        "period": (
            event.get("shotmapEvent", {})
                .get("period")
        ),
        "expected_goals": (
            event.get("shotmapEvent", {})
                 .get("expectedGoals")
        ),
        "card_type": card_type,
        "player_out_id": player_out_id,
        "player_out_name": player_out_name,
        "player_in_id": player_in_id,
        "player_in_name": player_in_name,
        "minutes_added": minutes_added,
        "event_description": (
            event.get("assistStr")
        )
    }

    event_records.append(record)
    
# print ("Event_Records: ", event_records[0]);

## Database insert statement for Matches table
match_insert = text("""
INSERT INTO soccer.matches
(
    match_id,
    competition,
    match_date,
    home_team,
    away_team,
    home_score,
    away_score,
    winner
)
VALUES
(
    :match_id,
    :competition,
    :match_date,
    :home_team,
    :away_team,
    :home_score,
    :away_score,
    :winner
)
ON CONFLICT (match_id)
DO NOTHING;
""")

## Database insert statement for Match Events table
event_insert = text("""
INSERT INTO soccer.match_events
(
    event_id,
    match_id,
    minute,
    minute_added,
    event_type,
    player_id,
    player_name,
    team_side,
    home_score_before,
    away_score_before,
    home_score_after,
    away_score_after,
    assist_player_id,
    assist_player_name,
    shot_type,
	situation,
	period,
    is_own_goal,
    card_type,
    player_out_id,
    player_out_name,
    player_in_id,
    player_in_name,
    minutes_added,
    expected_goals,
    event_description
)
VALUES
(
    :event_id,
    :match_id,
    :minute,
    :minute_added,
    :event_type,
    :player_id,
    :player_name,
    :team_side,
    :home_score_before,
    :away_score_before,
    :home_score_after,
    :away_score_after,
    :assist_player_id,
    :assist_player_name,
    :shot_type,
    :situation,
    :period,
    :is_own_goal,
    :card_type,
    :player_out_id,
    :player_out_name,
    :player_in_id,
    :player_in_name,
    :minutes_added,
    :expected_goals,
    :event_description
)
ON CONFLICT (match_id, event_id)
DO NOTHING;
""")

## Database insert statement for Match Stats table
stat_insert = text("""
INSERT INTO soccer.match_stats
(
    match_id,
    stat_key,
    stat_title,
    home_value,
    away_value
)
VALUES
(
    :match_id,
    :stat_key,
    :stat_title,
    :home_value,
    :away_value
);
""")

## Insert data into the database
with engine.begin() as conn:

    conn.execute(match_insert, match_data)

    for event in event_records:
        conn.execute(event_insert, event)

    for stat in stat_records:
        conn.execute(stat_insert, stat)

print("Match loaded successfully (Match ID:", match_data["match_id"], ")")