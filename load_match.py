def load_match(
    match_data,
    event_records,
    stat_records
):
    """
    Load match data into the database.

    Args:
        match_data: Dictionary containing match details.
        event_records: List of dictionaries containing event details.
        stat_records: List of dictionaries containing match stats.
    """
    from sqlalchemy import text
    from database import engine
    
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

    print(
        f"Loaded Match {match_data['match_id']} | "
        f"{len(event_records)} events | "
        f"{len(stat_records)} stats"
    )