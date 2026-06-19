# fetch_matches.py

import requests
import json

MATCH_ID = "4667751"

## Fetch Match details
url_details = (
    f"https://www.fotmob.com/api/data/matchDetails"
    f"?matchId={MATCH_ID}"
)

response_details = requests.get(url_details)

print(response_details.status_code)

data_details = response_details.json()

with open("sample_match.json", "w", encoding="utf-8") as f:
    json.dump(data_details, f, indent=4)

print("Match Details JSON saved successfully!")

# ## Fetch Match Insights
# url_Insights = (
#     f"https://www.fotmob.com/api/data/matchInsights"
#     f"?matchId={MATCH_ID}"
# )

# response_insights = requests.get(url_Insights)

# print(response_insights.status_code)
# # print(response_details.json())

# data_insights = response_insights.json()

# with open("sample_match_insights.json", "w", encoding="utf-8") as f:
#     json.dump(data_insights, f, indent=4)

# print("Match Insights JSON saved successfully!")

# print(data.keys())

# print(data["general"].keys())

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

print ("Match_Data: ", match_data);

## Data for Match Stats table
match_stats = {
    "match_id": match_data["match_id"],

    "possession_home": 60,
    "possession_away": 40,

    "xg_home": 1.46,
    "xg_away": 0.07,

    "shots_home": 16,
    "shots_away": 3,

    "shots_on_target_home": 4,
    "shots_on_target_away": 2
}

print ("Match_Stats: ", match_stats);

## Data for Match Events table
event_list = data_details["content"]["matchFacts"]["events"]["events"]

event_records = []

for event in event_list:

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

        "expected_goals": (
            event.get("shotmapEvent", {})
                 .get("expectedGoals")
        ),

        "event_description": (
            event.get("assistStr")
        )
    }

    event_records.append(record)
    
print ("Event_Records: ", event_records[0]);