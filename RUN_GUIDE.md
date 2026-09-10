# FPL Agent v4: Full Run Guide

The version of this in README.md is now out of date on a few points. This is
the corrected version, current as of the fixtures/backfill/check_squad fixes.

## One-time setup

```bash
python -m venv .venv
```
Windows: `.venv\Scripts\activate`
Mac/Linux: `source .venv/bin/activate`

```bash
pip install -r requirements.txt
cp .env.example .env        # then edit .env with real values, see below
createdb fpl_agent           # or point DATABASE_URL at an existing Postgres instance
python -c "from db.connection import init_schema; init_schema()"
```

In `.env`, set:
```
DATABASE_URL=postgresql://user:pass@localhost:5432/fpl_agent
FPL_CURRENT_GW=4
```
`FPL_CURRENT_GW` is the important one. It is not detected automatically from
the FPL API. If you do not set it, `config.py` falls back to a hardcoded
default of 4. Every week, before you run anything, update this to the
gameweek you are about to ingest, or every script will silently keep
labeling data with the old number instead of failing loudly.

## Every gameweek, run this in order

**1. Ingest the current gameweek and refresh fixtures.**
```bash
python ops/retrain_job.py
```
This now also writes the `fixtures` table (teams, kickoff, and final scores
once played), which it did not do before. You will see `tqdm` progress bars
for teams, players, fixtures, and the snapshot itself.

**2. Backfill full player history (only needed once early season, or after a gap).**
```bash
python -m ingestion.historical_backfill
```
This previously had no entrypoint and silently did nothing when run. It now
reads every player from the `players` table and pulls their real per-GW
history. This is the slow step, one HTTP request per player, watch the
`tqdm` ETA. You do not need to re-run this every single week once your
history is caught up; `ops/retrain_job.py` keeps extending it incrementally.

**3. Retrain the models on the latest real data.**
```bash
python models/train_team_strength.py
python models/train_expected_minutes.py
```
Run these periodically, not necessarily every single gameweek. Re-run
`train_team_strength.py` whenever a batch of new fixtures has finished.
Re-run `train_expected_minutes.py` every few gameweeks as more history
accumulates, or whenever `ops/retrain_job.py` prints a calibration warning.

**4. Bring in your actual squad for the target gameweek.**
```bash
python import_squad.py --team_id 7379699 --gw 4
python check_squad.py --gw 4
```
`import_squad.py` always pulls the *previous* gameweek's finalized picks as
the baseline for the gameweek you pass in. `check_squad.py` now takes
`--gw` explicitly; it used to be hardcoded to GW4 and would silently check
the wrong week once you moved past it.

**5. Generate predictions for the target gameweek.**
```bash
python -m models.run_predictions --gw 4
```
Needs fixtures (step 1) and, ideally, trained models (step 3) to produce
meaningful numbers rather than falling back to heuristics everywhere.

**6. Get recommendations.**
```bash
python optimizers/run_all.py --gw 4
```
Prints the transfer and captaincy recommendation straight to the terminal.

**7. Or use the visual UI instead of/as well as step 6.**
```bash
streamlit run ui/app.py
```
Covers everything above plus the squad builder, wildcard optimizer, chip
timing, and recommendation tracking.

## Does this work for every future gameweek automatically?

Not hands-off, no. Two things need a human every week:
- **Bump `FPL_CURRENT_GW` in `.env`** before step 1. Nothing infers this from
  the FPL API's own "current event" flag.
- **Pass the correct `--gw` to `import_squad.py`, `check_squad.py`,
  `run_predictions.py`, and `optimizers/run_all.py`.** They do not share a
  single source of truth for "what gameweek is it," each one takes its own
  `--gw` argument.

Steps 2 and 3 (backfill, retraining) do not need to run every week, only
step 1, 4, 5, and 6 (or 7) do.
