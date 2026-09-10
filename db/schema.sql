-- Postgres warehouse schema for FPL Agent v5. Idempotent.

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
ALTER TABLE players ADD COLUMN IF NOT EXISTS first_name TEXT;
ALTER TABLE players ADD COLUMN IF NOT EXISTS second_name TEXT;

CREATE TABLE IF NOT EXISTS fixtures (
    fixture_id INT PRIMARY KEY, gw INT,
    home_team_id INT REFERENCES teams(team_id),
    away_team_id INT REFERENCES teams(team_id),
    kickoff TIMESTAMP, home_goals INT, away_goals INT
);

CREATE TABLE IF NOT EXISTS player_snapshots (
    snapshot_id BIGSERIAL PRIMARY KEY,
    player_id INT REFERENCES players(player_id),
    pulled_at TIMESTAMP DEFAULT now(),
    gw INT, minutes INT,
    season_total_points INT,
    season_goals_scored INT, season_assists INT,
    form NUMERIC, selected_by_percent NUMERIC, ict_index NUMERIC,
    expected_goals NUMERIC, expected_assists NUMERIC, expected_goals_conceded NUMERIC,
    now_cost NUMERIC, status TEXT, news TEXT
);
ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS season_goals_scored INT;
ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS season_assists INT;

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
    source TEXT NOT NULL,
    computed_at TIMESTAMP DEFAULT now(),
    UNIQUE (player_id, gw)
);
ALTER TABLE player_gw_points ADD COLUMN IF NOT EXISTS goals_scored INT DEFAULT 0;
ALTER TABLE player_gw_points ADD COLUMN IF NOT EXISTS assists INT DEFAULT 0;

CREATE TABLE IF NOT EXISTS team_strength (
    team_id INT REFERENCES teams(team_id), gw INT,
    attack_home NUMERIC, attack_away NUMERIC,
    defence_home NUMERIC, defence_away NUMERIC,
    PRIMARY KEY (team_id, gw)
);

CREATE TABLE IF NOT EXISTS predictions (
    prediction_id BIGSERIAL PRIMARY KEY,
    player_id INT, gw INT, model_version TEXT,
    xp_mean NUMERIC, xp_p10 NUMERIC, xp_p50 NUMERIC, xp_p90 NUMERIC,
    start_prob NUMERIC,
    xp_conditional NUMERIC,
    created_at TIMESTAMP DEFAULT now()
);
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS xp_conditional NUMERIC;
CREATE UNIQUE INDEX IF NOT EXISTS predictions_player_gw_model_uniq
    ON predictions(player_id, gw, model_version);

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
    created_at TIMESTAMP DEFAULT now(),
    actual_outcome JSONB, evaluated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_calibration (
    model_version TEXT, gw INT, bucket TEXT,
    predicted_rate NUMERIC, actual_rate NUMERIC, n INT,
    PRIMARY KEY (model_version, gw, bucket)
);

-- v5 additions
CREATE TABLE IF NOT EXISTS team_fixture_difficulty (
    team_id INT REFERENCES teams(team_id),
    gw INT,
    opponent_team_id INT REFERENCES teams(team_id),
    is_home BOOLEAN,
    fdr INT,
    PRIMARY KEY (team_id, gw, opponent_team_id)
);

CREATE TABLE IF NOT EXISTS player_features (
    player_id INT REFERENCES players(player_id),
    gw INT,
    form_3gw NUMERIC, form_6gw NUMERIC, form_10gw NUMERIC,
    minutes_trend NUMERIC,
    xgi_per_90 NUMERIC,
    injury_flag BOOLEAN DEFAULT FALSE,
    fdr_next_3 NUMERIC,
    computed_at TIMESTAMP DEFAULT now(),
    PRIMARY KEY (player_id, gw)
);

CREATE TABLE IF NOT EXISTS user_lineup (
    gw INT,
    player_id INT REFERENCES players(player_id),
    role TEXT CHECK (role IN ('START','BENCH_GK','BENCH_1','BENCH_2','BENCH_3')),
    bench_order INT,
    is_captain BOOLEAN DEFAULT FALSE,
    is_vice BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (gw, player_id)
);

CREATE TABLE IF NOT EXISTS backtest_results (
    model_version TEXT,
    gw INT,
    n_players INT,
    mae NUMERIC, rmse NUMERIC, spearman NUMERIC,
    captain_hit BOOLEAN,
    captain_predicted_pts NUMERIC,
    captain_actual_pts NUMERIC,
    oracle_pts NUMERIC,
    computed_at TIMESTAMP DEFAULT now(),
    PRIMARY KEY (model_version, gw)
);