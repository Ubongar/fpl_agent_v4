"""Daily entrypoint: ingest -> backfill new features -> re-run calibration ->
flag drift. Wire this into GitHub Actions (see .github/workflows/daily.yml)."""
import sys
from config import CURRENT_GW
from ingestion.fpl_source import run_daily_ingest, fetch_bootstrap
from validation.calibration import calibration_curve, is_well_calibrated

def main():
    print(f"[retrain_job] Ingesting GW{CURRENT_GW}...")
    n = run_daily_ingest(CURRENT_GW)
    print(f"[retrain_job] Snapshotted {n} players.")

    # Placeholder: pull last GW's start_prob predictions vs actual starts from DB
    # and check calibration. Wire real query once predictions table has rows.
    dummy_curve = calibration_curve([0.2, 0.5, 0.8], [0, 1, 1])
    ok = is_well_calibrated(dummy_curve)
    print(f"[retrain_job] Calibration OK: {ok}")
    if not ok:
        print("[retrain_job] WARNING: drift detected, consider retraining expected_minutes model.")
        sys.exit(1)

if __name__ == "__main__":
    main()
