# fetch_matches.py

import requests
import json

MATCH_ID = "4667751"

url = (
    f"https://www.fotmob.com/api/data/matchDetails"
    f"?matchId={MATCH_ID}"
)

response = requests.get(url)

print(response.status_code)
# print(response.json())

data = response.json()

with open("sample_match.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=4)

print("JSON saved successfully!")

# print(data.keys())

# print(data["general"].keys())

match_data = {
    "match_id": data["general"]["matchId"],
    "competition": data["general"]["leagueName"],
    "match_date": data["general"]["matchTimeUTCDate"],

    "home_team": data["general"]["homeTeam"]["name"],
    "away_team": data["general"]["awayTeam"]["name"],

    "home_score": data["header"]["teams"][0]["score"],
    "away_score": data["header"]["teams"][1]["score"],

    "winner": (
        data["general"]["homeTeam"]["name"]
        if data["header"]["teams"][0]["score"] >
           data["header"]["teams"][1]["score"]
        else data["general"]["awayTeam"]["name"]
    )
}

##Match Stats###
match_stats = {
    "match_id": match_id,

    "possession_home": 60,
    "possession_away": 40,

    "xg_home": 1.46,
    "xg_away": 0.07,

    "shots_home": 16,
    "shots_away": 3,

    "shots_on_target_home": 4,
    "shots_on_target_away": 2
}

events = []

for event in event_list:

    events.append({
        "minute": event["minute"],
        "event_type": event["eventType"],
        "player": event["playerName"],
        "team": event["teamName"]
    })