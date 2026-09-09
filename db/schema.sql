-- Postgres warehouse schema for FPL Agent v4

CREATE TABLE IF NOT EXISTS teams (
    team_id INT PRIMARY KEY, name TEXT, short_name TEXT
);

CREATE TABLE IF NOT EXISTS players (
    player_id INT PRIMARY KEY, web_name TEXT, team_id INT REFERENCES teams(team_id),
    position TEXT CHECK (position IN ('GK','DEF','MID','FWD')), now_cost NUMERIC
);

CREATE TABLE IF NOT EXISTS fixtures (
    fixture_id INT PRIMARY KEY, gw INT, home_team_id INT REFERENCES teams(team_id),
    away_team_id INT REFERENCES teams(team_id), kickoff TIMESTAMP,
    home_goals INT, away_goals INT
);

-- Immutable daily snapshot log. One row per player per pull, NEVER overwritten
-- and NEVER used directly for per-GW analysis -- season_total_points is
-- CUMULATIVE (as returned by bootstrap-static), not a per-gameweek score.
-- Per-GW figures live only in player_gw_points below.
CREATE TABLE IF NOT EXISTS player_snapshots (
    snapshot_id BIGSERIAL PRIMARY KEY,
    player_id INT REFERENCES players(player_id),
    pulled_at TIMESTAMP DEFAULT now(),
    gw INT,                                  -- the "current event" gw at time of pull
    minutes INT,                             -- cumulative season minutes at time of pull
    season_total_points INT,                 -- CUMULATIVE season total (bootstrap-static "total_points")
    form NUMERIC, selected_by_percent NUMERIC, ict_index NUMERIC,
    expected_goals NUMERIC, expected_assists NUMERIC, expected_goals_conceded NUMERIC,
    now_cost NUMERIC, status TEXT, news TEXT
);

-- Single source of truth for TRUE per-gameweek player performance.
-- Populated two ways, both idempotent thanks to the UNIQUE constraint:
--   (a) historical_backfill.py -- element-summary "history" rows, which are
--       genuinely per-fixture/per-GW already (no diffing needed)
--   (b) fpl_source.compute_gw_points_from_snapshots() -- diffs consecutive
--       season_total_points in player_snapshots once a gameweek completes
-- Models (rolling_form, expected_points, etc.) must ONLY read from this table,
-- never from player_snapshots.season_total_points directly.
CREATE TABLE IF NOT EXISTS player_gw_points (
    player_id INT REFERENCES players(player_id),
    gw INT NOT NULL,
    gw_points INT NOT NULL,
    minutes INT,
    ict_index NUMERIC,
    expected_goals NUMERIC,
    expected_assists NUMERIC,
    now_cost NUMERIC,
    source TEXT NOT NULL,                    -- 'backfill' | 'snapshot_diff'
    computed_at TIMESTAMP DEFAULT now(),
    UNIQUE (player_id, gw)                   -- <-- the constraint bug-fix #2 needed
);

CREATE TABLE IF NOT EXISTS team_strength (
    team_id INT REFERENCES teams(team_id), gw INT,
    attack_home NUMERIC, attack_away NUMERIC, defence_home NUMERIC, defence_away NUMERIC,
    PRIMARY KEY (team_id, gw)
);

CREATE TABLE IF NOT EXISTS predictions (
    prediction_id BIGSERIAL PRIMARY KEY, player_id INT, gw INT, model_version TEXT,
    xp_mean NUMERIC, xp_p10 NUMERIC, xp_p50 NUMERIC, xp_p90 NUMERIC, start_prob NUMERIC,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recommendations (
    rec_id BIGSERIAL PRIMARY KEY, gw INT, rec_type TEXT, payload JSONB,
    created_at TIMESTAMP DEFAULT now(), actual_outcome JSONB, evaluated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_calibration (
    model_version TEXT, gw INT, bucket TEXT, predicted_rate NUMERIC, actual_rate NUMERIC, n INT,
    PRIMARY KEY (model_version, gw, bucket)
);
