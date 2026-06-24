import json
import requests
import pycountry
import country_converter as coco


def fetch_from_api(url):
    """Fetch JSON data from the FotMob API."""
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def save_json_to_file(data, filename):
    """Save a JSON-serializable object to a file."""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def build_match_json_filename(match_id, home_team, away_team):
    """Build a safe filename for the match JSON export."""
    safe_home = home_team.replace(" ", "_").replace("/", "-")
    safe_away = away_team.replace(" ", "_").replace("/", "-")
    return f"match_{match_id}_{safe_home}_vs_{safe_away}.json"


def build_match_details_url(match_id):
    """Build the FotMob match details URL for a match ID."""
    return f"https://www.fotmob.com/api/data/matchDetails?matchId={match_id}"


def build_daily_matches_url(match_date):
    """Build the FotMob daily matches URL for a given date."""
    return (
        f"https://www.fotmob.com/api/data/matches"
        f"?date={match_date}"
        f"&timezone=America/Chicago"
        f"&ccode3=USA"
        f"&includeNextDayLateNight=true"
    )

def get_country_name(code):
    """Return the country name for a given ISO 3166-1 alpha-3 code."""
    
    ## Handle special cases which FOTMOB stores differently than ISO 3166-1 alpha-3 standard.
    SPECIAL_CODES = {
    "INT": "International",
    "ENG": "England",
    "SCO": "Scotland",
    "WAL": "Wales",
    "NIR": "Northern Ireland",
    }

    if not code:
        return None

    code = code.strip().upper()

    if code in SPECIAL_CODES:
        return SPECIAL_CODES[code]

    converter = coco.CountryConverter()
    country_name = converter.convert(code, src="FIFA", to="name")

    if country_name and country_name != "not found":
        return country_name

    return code