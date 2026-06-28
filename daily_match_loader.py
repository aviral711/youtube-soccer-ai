import argparse
from datetime import date, datetime

from database import engine, text
from fetch_matches import fetch_match_details
from common_utils import (
    build_daily_matches_url,
    fetch_from_api,
)


def get_daily_matches(match_date):
    """Fetch the daily matches JSON for the given date."""
    url = build_daily_matches_url(match_date)
    return fetch_from_api(url)


def build_match_record(match, league_name):
    """Build a lightweight metadata record for a daily match."""
    return {
        "match_id": match.get("id"),
        "league_name": league_name,
        "home_team": match["home"]["name"],
        "away_team": match["away"]["name"],
        "finished": match["status"].get("finished", False),
    }


def extract_match_ids(data):
    """Extract match metadata records from the API response."""
    match_list = []
    leagues = data.get("leagues", [])

    for league in leagues:
        league_name = league.get("name")
        for match in league.get("matches", []):
            match_list.append(build_match_record(match, league_name))

    return match_list


def match_exists(match_id):
    """Return True if the match is already in the database."""
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT 1
                FROM soccer.matches
                WHERE match_id = CAST(:match_id AS varchar)
            """),
            {"match_id": match_id}
        )
        return result.fetchone() is not None


def should_load_match(match):
    """Return True if the match should be loaded."""
    return match["finished"] and not match_exists(match["match_id"])


def load_match_if_new(match):
    """Load the match if finished and not already loaded."""
    if not should_load_match(match):
        return False

    match_id = match["match_id"]
    print(f"Loading {match_id}: {match['home_team']} vs {match['away_team']}")
    fetch_match_details(match_id)
    return True


def load_daily_matches(match_date):
    """Fetch and load completed new matches for a date."""
    daily_data = get_daily_matches(match_date)
    matches = extract_match_ids(daily_data)

    for match in matches:
        load_match_if_new(match)

def normalize_match_date(match_date):
    """Normalize the input date string to YYYYMMDD, defaulting to today."""
    if not match_date:
        return date.today().strftime("%Y%m%d")

    cleaned = match_date.strip()
    try:
        if "-" in cleaned:
            parsed_date = datetime.strptime(cleaned, "%Y-%m-%d").date()
        else:
            parsed_date = datetime.strptime(cleaned, "%Y%m%d").date()
    except ValueError:
        raise ValueError(
            "Invalid date format. Use YYYYMMDD or YYYY-MM-DD. "
            f"Received: {match_date}"
        )

    return parsed_date.strftime("%Y%m%d")

def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch and load completed matches for a given date."
    )
    parser.add_argument(
        "match_date",
        nargs="?",
        default=None,
        help="Date in YYYYMMDD or YYYY-MM-DD format. Defaults to today.",
    )
    args = parser.parse_args()

    if args.match_date is not None:
        try:
            args.match_date = normalize_match_date(args.match_date)
        except ValueError as exc:
            parser.error(str(exc))

    return args


def main(match_date=None):
    load_daily_matches(normalize_match_date(match_date))


if __name__ == "__main__":
    args = parse_args()
    main(args.match_date)
