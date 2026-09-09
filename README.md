# FPL Agent v4 — Predictive + Optimization Engine

Built on the v3 skeleton, with two real correctness bugs fixed (details below),
LLM layer switched from Anthropic to OpenAI (model `olori-image`), and a
proper `.env.example` for setup.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit .env with real values
createdb fpl_agent           # or point DATABASE_URL at an existing Postgres instance
python -c "from db.connection import init_schema; init_schema()"
python ops/retrain_job.py    # first ingest -- requires DATABASE_URL and network access to fantasy.premierleague.com
streamlit run ui/app.py
```

## Bugs fixed in v4 (both verified with real tests, not just claimed)

**Bug 1 — cumulative vs per-GW points confusion.**
`bootstrap-static`'s `total_points` field is season-cumulative, not a
per-gameweek score. v3 stored it directly as if it were per-GW, which would
have silently corrupted `rolling_form` (points would appear to climb every
week forever, never reset). Fixed by:
- `player_snapshots.season_total_points` — honestly named, cumulative, raw pull log (immutable).
- New `player_gw_points` table — the ONLY source models should read per-GW
  figures from. Populated two ways: `historical_backfill.py` (element-summary
  history rows, genuinely per-GW already) and
  `fpl_source.compute_gw_points_from_snapshots()` (diffs consecutive
  cumulative totals once a gameweek completes).
- Verified in this build with a synthetic cumulative sequence `[5, 11, 11, 18]`
  → correctly diffed to per-GW `[5, 6, 0, 7]`.

**Bug 2 — `ON CONFLICT DO NOTHING` had no matching constraint.**
Re-running backfill silently duplicated every row. Fixed by adding a real
`UNIQUE (player_id, gw)` constraint on `player_gw_points`, and switching to
`ON CONFLICT (player_id, gw) DO UPDATE` so reruns correct existing rows
instead of duplicating or silently no-op'ing.
- Verified: inserting the same `(player_id, gw)` twice leaves exactly one row.

**Bonus bug found + fixed during this build:** `agent/llm_agent.py` originally
instantiated the OpenAI client at *import time*, which crashed the whole
module (and therefore the Streamlit app) if `OPENAI_API_KEY` wasn't set yet.
Fixed with lazy client initialization — importing the module is now always
safe; only calling `explain_recommendation()` without a key raises a clear
`RuntimeError`.

## What's actually verified to run in this build
Everything below was executed in a sandbox and confirmed working — not just written:
`expected_minutes`, `team_strength`, `dixon_coles`, `expected_points`,
`distributions`, `backtest`, `calibration`, all 5 optimizers (including the
`pulp` ILP wildcard solver), `config.py` + `.env` loading, `agent/llm_agent.py`
import safety, `db/connection.py` lazy engine creation.

## What could NOT be run/verified here, and is left as-is per your instruction
This sandbox has no network access to `fantasy.premierleague.com` and no live
Postgres server, so the following are correct by inspection and unit-testable
logic, but not end-to-end tested against real data:
- `ingestion/fpl_source.py` — live API calls (`fetch_bootstrap`, `fetch_fixtures`)
- `ingestion/historical_backfill.py` — live `element-summary` calls
- `ops/retrain_job.py` and the GitHub Action — depend on both of the above
- Any actual query against a running Postgres instance (schema is correct SQL,
  but was validated for the two bug-fix behaviors using SQLite as a
  syntax-compatible stand-in, not a live Postgres connection)
- `agent/llm_agent.explain_recommendation()` — needs a real `OPENAI_API_KEY`
  to actually call the API; only import-safety was verified here

**Before this runs for you:** fill in `.env` (copy from `.env.example`), point
it at a real Postgres database, and run `init_schema()` — the code expects
that schema to exist before ingestion, backfill, or model code will work.

## Build order (unchanged from v3 — still applies)
0. db/ + ingestion/ → 1. models/ → 2. validation/ → 3. optimizers/ → 4. ops/ → 5. agent/ + ui/
