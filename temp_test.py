import requests
import json
from sqlalchemy import text
from common_utils import save_json_to_file
from database import engine

MATCH_ID = "5147581"

## Fetch Match details
url_details = (
    f"https://www.fotmob.com/api/data/matchDetails"
    f"?matchId={MATCH_ID}"
)

response_details = requests.get(url_details)

# print(response_details.status_code)

data_details = response_details.json()
save_json_to_file(data_details, "sample_match_5147581.json")
## Data for Match Stats table
# stat_records = []

# stat_groups = data_details["content"]["stats"]["Periods"]["All"]["stats"]

# for group in stat_groups:

#     if isinstance(group.get("stats"), list):

#         for stat in group["stats"]:
#             if stat.get("type") == "title":
#                 continue

#             record = {
#                 "match_id": data_details["general"]["matchId"],
#                 "stat_key": stat.get("key"),
#                 "stat_title": stat.get("title"),
#                 "home_value": str(stat["stats"][0]),
#                 "away_value": str(stat["stats"][1])
#             }

#             stat_records.append(record)

# for stat in stat_records:
#     if stat["stat_key"] == "accurate_passes":
#         print(stat)