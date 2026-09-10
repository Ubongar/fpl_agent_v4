# FPL Agent v4: Predictive + Optimization Engine

An end-to-end Fantasy Premier League decision-support system. It ingests real
data from the official FPL API, models expected points per player per
fixture, tracks your actual 15-man squad, and turns predictions into concrete
transfer, captaincy, wildcard, and chip-timing recommendations through a
Streamlit interface.

## Pipeline

```
ingestion/  ->  models/  ->  validation/  ->  optimizers/  ->  ops/  ->  agent/ + ui/
```

- **ingestion/** pulls live data from `fantasy.premierleague.com` (bootstrap,
  fixtures, per-player history) and writes immutable snapshots plus a
  per-gameweek points table.
- **models/** computes expected minutes, team strength ratings, and expected
  points per player per fixture (`run_predictions.py` writes these into the
  `predictions` table).
- **validation/** checks calibration and backtests predictions against actual
  outcomes.
- **optimizers/** turns predictions into recommendations: single transfers,
  a full wildcard squad (ILP via `pulp`), captaincy ranking, chip timing
  (Bench Boost, Triple Captain, Free Hit), and DGW/BGW handling.
- **ops/retrain_job.py** runs the daily ingest and a real calibration check.
- **agent/llm_agent.py** (OpenAI, model `olori-image`) explains logged
  recommendations in plain language.
- **ui/app.py** is the Streamlit command center tying all of the above
  together, including a squad builder (`ui/pitch.py`).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit .env with real values
createdb fpl_agent           # or point DATABASE_URL at an existing Postgres instance
python -c "from db.connection import init_schema; init_schema()"

# 1. Ingest and backfill real data
python ops/retrain_job.py                       # first ingest of the current gameweek
python -m ingestion.historical_backfill          # per-GW history for existing players

# 2. Train the models on real history
python -m models.train_team_strength             # needs finished fixtures
python -m models.train_expected_minutes          # needs several gameweeks of history

# 3. Bring in your actual squad and generate predictions
python import_squad.py --team_id 7379699 --gw 4
python -m models.run_predictions --gw 4

python optimizers/run_all.py --gw 4
# 4. Launch the UI
streamlit run ui/app.py
```

Each training and prediction script prints a clear message and skips itself
if there is not yet enough real data to run on, instead of producing
misleading output.

## What this build adds on top of the v3 skeleton

- **Real squad tracking.** New `user_squad` and `team_meta` tables,
  `import_squad.py` to pull your actual 15 from the FPL API, and
  `check_squad.py` to verify it is complete before running the optimizers.
- **`models/run_predictions.py`.** The `predictions` table existed in the
  schema from the start, but nothing wrote to it. This script now populates
  it per player per fixture using real team strength ratings, Dixon-Coles,
  and a Bayesian-shrunk goal/assist share model, correctly summing DGW legs
  and skipping BGW players entirely rather than inserting a fabricated 0.
- **A trained `expected_minutes` model.** `train_expected_minutes.py` fits a
  logistic regression on real `player_gw_points` history. `expected_minutes()`
  loads it automatically and falls back to the original recency-weighted
  heuristic only when no trained model or too little history exists yet.
- **A trained `team_strength` model.** `train_team_strength.py` computes real
  home/away attack and defence ratings from actual fixture results, replacing
  the placeholder neutral ratings used previously.
- **A real calibration check.** `ops/retrain_job.py` now compares actual
  starts against predicted `start_prob` instead of running a hardcoded dummy
  curve, and skips the check with a clear message if there is not yet enough
  backfilled history.
- **A fully wired Streamlit UI.** Every tab (Overview, Predictions,
  Transfers, Wildcard, Captaincy, Chips, Tracking, Ask the Agent) now queries
  the live database instead of showing demo data, with warnings that point
  you to the right script when upstream data is missing.
- **Two squad-builder UIs.** `ui/pitch.py` is a dropdown-based, position-
  locked squad builder used by the Transfers tab. `ui/pitch_elements.py` is a
  drag-and-drop alternative built on `streamlit-elements`; its drag handlers
  are currently placeholders, so treat it as a work in progress rather than
  the primary builder.
- **Schema additions.** `season_goals_scored` and `season_assists` columns on
  `player_snapshots` and `player_gw_points`, and a unique index on
  `predictions(player_id, gw, model_version)` so reruns update rather than
  duplicate rows.

## Bugs fixed versus v3 (verified with real tests)

**Bug 1: cumulative vs per-GW points confusion.**
`bootstrap-static`'s `total_points` field is season-cumulative, not a
per-gameweek score. v3 stored it directly as if it were per-GW, which would
have silently corrupted rolling form (points would appear to climb every
week forever, never reset). Fixed by:
- `player_snapshots.season_total_points`: honestly named, cumulative, raw
  pull log (immutable).
- `player_gw_points`: the only table models should read per-GW figures from.
  Populated two ways, `historical_backfill.py` (already per-GW from the FPL
  API) and `fpl_source.compute_gw_points_from_snapshots()` (diffs consecutive
  cumulative totals once a gameweek completes).
- Verified with a synthetic cumulative sequence `[5, 11, 11, 18]`, which
  correctly diffs to per-GW `[5, 6, 0, 7]`.

**Bug 2: `ON CONFLICT DO NOTHING` had no matching constraint.**
Re-running backfill silently duplicated every row. Fixed by adding a real
`UNIQUE (player_id, gw)` constraint on `player_gw_points`, and switching to
`ON CONFLICT (player_id, gw) DO UPDATE` so reruns correct existing rows
instead of duplicating or silently no-opping.
- Verified: inserting the same `(player_id, gw)` twice leaves exactly one row.

**Bonus bug: `agent/llm_agent.py` crashed at import time** if
`OPENAI_API_KEY` wasn't set, which took down the whole Streamlit app. Fixed
with lazy client initialization; importing the module is now always safe,
and only calling `explain_recommendation()` without a key raises a clear
`RuntimeError`.

## What is verified to run in this build

Executed in a sandbox and confirmed working: `expected_minutes` (both the
heuristic and trained-model paths), `team_strength` and
`train_team_strength.py`'s pure history-building functions, `dixon_coles`,
`expected_points`, `distributions`, `backtest`, `calibration`, all 5
optimizers (including the `pulp` ILP wildcard solver), `config.py` and
`.env` loading, `agent/llm_agent.py` import safety, and
`db/connection.py` lazy engine creation.

## What could not be run or verified here

This sandbox has no network access to `fantasy.premierleague.com` and no
live Postgres server, so the following are correct by inspection and
unit-testable logic but not end-to-end tested against real data:
- `ingestion/fpl_source.py` and `ingestion/historical_backfill.py` (live API
  calls)
- `import_squad.py` (live API call to fetch your actual picks)
- `ops/retrain_job.py` and the GitHub Action (depend on the above)
- `models/train_team_strength.py` and `models/run_predictions.py` against a
  real, populated Postgres instance
- Any query against a live Postgres instance in general (schema is correct
  SQL, validated for the two bug-fix behaviors using SQLite as a
  syntax-compatible stand-in)
- `agent/llm_agent.explain_recommendation()` (needs a real `OPENAI_API_KEY`
  to actually call the API; only import-safety was verified here)

**Before this runs for you:** fill in `.env` (copy from `.env.example`),
point it at a real Postgres database, run `init_schema()`, and work through
the Setup steps above in order. The prediction pipeline expects team
strength and expected-minutes training data before `run_predictions.py` will
produce meaningful output.

## Build order (unchanged from v3)

0. `db/` + `ingestion/` -> 1. `models/` -> 2. `validation/` -> 3.
`optimizers/` -> 4. `ops/` -> 5. `agent/` + `ui/`