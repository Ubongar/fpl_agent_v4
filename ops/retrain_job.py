"""Daily entrypoint: ingest -> calibrate -> flag drift."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from ingestion.fpl_source import run_daily_ingest
from db.connection import get_session
from sqlalchemy import text
from validation.calibration import calibration_curve, is_well_calibrated


def check_real_calibration():
    from models.expected_minutes import expected_minutes

    session = get_session()
    rows = session.execute(text("""
        SELECT player_id, gw, minutes FROM player_gw_points ORDER BY player_id, gw
    """)).fetchall()
    session.close()

    if len(rows) < 20:
        print(f"[retrain_job] Only {len(rows)} player_gw_points rows.")
        return None

    by_player = {}
    for r in rows:
        by_player.setdefault(r.player_id, []).append(r.minutes)

    predicted, actual = [], []
    for pid, minutes_list in by_player.items():
        if len(minutes_list) < 3:
            continue
        history, this_gw_minutes = minutes_list[:-1], minutes_list[-1]
        pred = expected_minutes(history)
        predicted.append(pred.get("appearance_prob", pred.get("start_prob", 0.5)))
        actual.append(1 if this_gw_minutes >= 60 else 0)

    if not predicted:
        print("[retrain_job] Not enough history depth.")
        return None

    curve = calibration_curve(predicted, actual)
    print(f"[retrain_job] Calibration curve (n={len(predicted)}): {curve}")
    return is_well_calibrated(curve)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, default=None)
    args = parser.parse_args()

    n, gw = run_daily_ingest(args.gw)
    print(f"[retrain_job] Ingested GW{gw}. Snapshotted {n} players.")

    ok = check_real_calibration()
    if ok is None:
        print("[retrain_job] Calibration check skipped.")
    else:
        print(f"[retrain_job] Calibration OK: {ok}")
        if not ok:
            print("[retrain_job] WARNING: drift detected.")
            sys.exit(1)


if __name__ == "__main__":
    main()