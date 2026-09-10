-- Postgres warehouse schema for FPL Agent v4

CREATE TABLE IF NOT EXISTS teams (
    team_id INT PRIMARY KEY, name TEXT, short_name TEXT
);

CREATE TABLE IF NOT EXISTS players (
    player_id INT PRIMARY KEY,
    web_name TEXT,
    first_name TEXT,
    second_name TEXT,
    team_id INT REFERENCES teams(team_id),
    position TEXT CHECK (position IN ('GK','DEF','MID','FWD')),
    now_cost NUMERIC
);
-- Safe migrations for existing DBs (add columns if the table already existed)
ALTER TABLE players ADD COLUMN IF NOT EXISTS first_name TEXT;
ALTER TABLE players ADD COLUMN IF NOT EXISTS second_name TEXT;

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
    season_goals_scored INT,                 -- CUMULATIVE season goals (bootstrap-static "goals_scored")
    season_assists INT,                      -- CUMULATIVE season assists (bootstrap-static "assists")
    form NUMERIC, selected_by_percent NUMERIC, ict_index NUMERIC,
    expected_goals NUMERIC, expected_assists NUMERIC, expected_goals_conceded NUMERIC,
    now_cost NUMERIC, status TEXT, news TEXT
);
ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS season_goals_scored INT;
ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS season_assists INT;

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
    goals_scored INT DEFAULT 0,
    assists INT DEFAULT 0,
    ict_index NUMERIC,
    expected_goals NUMERIC,
    expected_assists NUMERIC,
    now_cost NUMERIC,
    source TEXT NOT NULL,                    -- 'backfill' | 'snapshot_diff'
    computed_at TIMESTAMP DEFAULT now(),
    UNIQUE (player_id, gw)
);
ALTER TABLE player_gw_points ADD COLUMN IF NOT EXISTS goals_scored INT DEFAULT 0;
ALTER TABLE player_gw_points ADD COLUMN IF NOT EXISTS assists INT DEFAULT 0;

CREATE TABLE IF NOT EXISTS team_strength (
    team_id INT REFERENCES teams(team_id), gw INT,
    attack_home NUMERIC, attack_away NUMERIC, defence_home NUMERIC, defence_away NUMERIC,
    PRIMARY KEY (team_id, gw)
);

-- Predictions table. The UNIQUE index below is what allows run_predictions.py
-- to upsert idempotently instead of duplicating rows on every rerun. Do NOT
-- drop it -- you already lost a day to exactly this class of bug in v3.
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id BIGSERIAL PRIMARY KEY, player_id INT, gw INT, model_version TEXT,
    xp_mean NUMERIC, xp_p10 NUMERIC, xp_p50 NUMERIC, xp_p90 NUMERIC, start_prob NUMERIC,
    created_at TIMESTAMP DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS predictions_player_gw_model_uniq
    ON predictions(player_id, gw, model_version);

-- Nothing previously tracked "your actual 15" anywhere -- required by
-- Transfers/Captaincy/Chips, which all act on the manager's own squad,
-- not the full player pool.
CREATE TABLE IF NOT EXISTS user_squad (
    player_id INT REFERENCES players(player_id),
    gw INT NOT NULL,
    bought_price NUMERIC,
    is_starting BOOLEAN DEFAULT true,
    is_captain BOOLEAN DEFAULT false,
    PRIMARY KEY (player_id, gw)
);

CREATE TABLE IF NOT EXISTS team_meta (
    gw INT PRIMARY KEY,
    bank NUMERIC NOT NULL DEFAULT 0,
    free_transfers INT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS recommendations (
    rec_id BIGSERIAL PRIMARY KEY, gw INT, rec_type TEXT, payload JSONB,
    created_at TIMESTAMP DEFAULT now(), actual_outcome JSONB, evaluated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_calibration (
    model_version TEXT, gw INT, bucket TEXT, predicted_rate NUMERIC, actual_rate NUMERIC, n INT,
    PRIMARY KEY (model_version, gw, bucket)
);