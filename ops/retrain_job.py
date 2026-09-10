"""Daily entrypoint: ingest -> backfill new features -> re-run calibration ->
flag drift. Wire this into GitHub Actions (see .github/workflows/daily.yml).

Auto-detects the current gameweek from the FPL API's own bootstrap-static
is_current/is_next flags (see ingestion.fpl_source.get_current_gw) instead of
requiring a manually maintained FPL_CURRENT_GW env var. Pass --gw to override
this and force a specific gameweek instead, e.g. when reprocessing a past one."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from ingestion.fpl_source import run_daily_ingest
from db.connection import get_session
from sqlalchemy import text
from validation.calibration import calibration_curve, is_well_calibrated

def check_real_calibration():
    """Compares expected_minutes' start_prob (recomputed from minutes history
    already in player_gw_points) against whether each player actually started
    (minutes > 0) that gameweek. Returns None if there's not yet enough
    backfilled history to check (needs at least 2 prior GWs per player)."""
    from models.expected_minutes import expected_minutes

    session = get_session()
    rows = session.execute(text("""
        SELECT player_id, gw, minutes FROM player_gw_points ORDER BY player_id, gw
    """)).fetchall()
    session.close()

    if len(rows) < 20:
        print(f"[retrain_job] Only {len(rows)} player_gw_points rows -- not enough "
              f"backfilled history yet to check calibration. Run historical_backfill first.")
        return None

    by_player = {}
    for r in rows:
        by_player.setdefault(r.player_id, []).append(r.minutes)

    predicted, actual = [], []
    for pid, minutes_list in by_player.items():
        if len(minutes_list) < 3:
            continue  # need prior history to predict the next GW
        history, this_gw_minutes = minutes_list[:-1], minutes_list[-1]
        pred = expected_minutes(history)
        predicted.append(pred["start_prob"])
        actual.append(1 if this_gw_minutes > 0 else 0)

    if not predicted:
        print("[retrain_job] Not enough per-player history depth yet to check calibration.")
        return None

    curve = calibration_curve(predicted, actual)
    print(f"[retrain_job] Real calibration curve (n={len(predicted)} players): {curve}")
    return is_well_calibrated(curve)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, default=None,
                         help="Force a specific gameweek instead of auto-detecting "
                              "the current one from the FPL API.")
    args = parser.parse_args()

    n, gw = run_daily_ingest(args.gw)
    print(f"[retrain_job] Ingested GW{gw}. Snapshotted {n} players.")

    ok = check_real_calibration()
    if ok is None:
        print("[retrain_job] Calibration check skipped (insufficient data).")
    else:
        print(f"[retrain_job] Calibration OK: {ok}")
        if not ok:
            print("[retrain_job] WARNING: drift de tected, consider retraining expected_minutes model.")
            sys.exit(1)

if __name__ == "__main__":
    main()