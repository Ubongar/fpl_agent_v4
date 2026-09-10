"""Walk-forward backtest. Writes to backtest_results.

Prints a per-GW progress line so you know it's moving. When --rerun is set,
run_predictions() itself shows its own tqdm bar per GW."""
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import numpy as np
from scipy.stats import spearmanr
from db.connection import get_session
from sqlalchemy import text
from models.run_predictions import run_predictions


def _log(msg):
    print(f"[backtest] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def _fetch_actual(session, gw):
    rows = session.execute(text(
        "SELECT player_id, gw_points FROM player_gw_points WHERE gw = :gw"
    ), dict(gw=gw)).fetchall()
    return {r.player_id: float(r.gw_points) for r in rows}


def _fetch_predictions(session, gw):
    rows = session.execute(text("""
        SELECT player_id, xp_mean, xp_p90, start_prob
        FROM predictions WHERE gw = :gw
    """), dict(gw=gw)).fetchall()
    return {r.player_id: {
        "xp_mean": float(r.xp_mean or 0),
        "xp_p90": float(r.xp_p90 or 0),
        "start_prob": float(r.start_prob or 0)} for r in rows}


def score_gw(session, gw):
    preds = _fetch_predictions(session, gw)
    actuals = _fetch_actual(session, gw)
    common = sorted(set(preds) & set(actuals))
    if len(common) < 20:
        _log(f"GW{gw}: only {len(common)} overlapping players — skipping.")
        return None

    p = np.array([preds[pid]["xp_mean"] for pid in common])
    a = np.array([actuals[pid] for pid in common])

    mae = float(np.mean(np.abs(p - a)))
    rmse = float(np.sqrt(np.mean((p - a) ** 2)))
    rho = float(spearmanr(p, a).correlation) if len(common) > 2 else 0.0

    # Top-N metrics that actually matter for FPL decisions
    top30_idx = np.argsort(-p)[:30]
    top30_mae = float(np.mean(np.abs(p[top30_idx] - a[top30_idx])))
    top10_idx = np.argsort(-p)[:10]
    top10_precision = float(np.mean(a[top10_idx] >= 8.0))

    top_pid = common[int(np.argmax(p))]
    captain_pred = preds[top_pid]["xp_mean"]
    captain_actual = actuals[top_pid]
    oracle = max(actuals[pid] for pid in common)
    captain_hit = captain_actual >= 8.0

    _log(f"GW{gw}: n={len(common)}  MAE={mae:.3f}  top30_MAE={top30_mae:.3f}  "
         f"spearman={rho:.3f}  top10_prec={top10_precision:.2f}  "
         f"captain={captain_actual}  oracle={oracle}")

    return {
        "gw": gw, "n_players": len(common),
        "mae": round(mae, 3), "rmse": round(rmse, 3),
        "spearman": round(rho, 3),
        "captain_hit": captain_hit,
        "captain_predicted_pts": round(captain_pred, 2),
        "captain_actual_pts": round(captain_actual, 2),
        "oracle_pts": round(oracle, 2),
    }


def run_backtest(start_gw, end_gw, model_version="v5", rerun_predictions=False):
    session = get_session()
    results = []
    total = end_gw - start_gw + 1
    try:
        _log(f"Backtest range: GW{start_gw} → GW{end_gw} "
             f"({total} GW{'s' if total != 1 else ''}), "
             f"rerun_predictions={rerun_predictions}")
        for i, gw in enumerate(range(start_gw, end_gw + 1), 1):
            _log(f"===== GW{gw} ({i}/{total}) =====")
            if rerun_predictions:
                _log(f"GW{gw}: re-running predictions (this is the slow step)…")
                t0 = time.time()
                run_predictions(gw)
                _log(f"GW{gw}: predictions refreshed in {time.time() - t0:.1f}s.")
            else:
                _log(f"GW{gw}: using existing predictions from DB.")

            _log(f"GW{gw}: scoring against actuals…")
            row = score_gw(session, gw)
            if row is None:
                continue
            row["model_version"] = model_version
            session.execute(text("""
                INSERT INTO backtest_results
                    (model_version, gw, n_players, mae, rmse, spearman,
                     captain_hit, captain_predicted_pts, captain_actual_pts,
                     oracle_pts, computed_at)
                VALUES (:mv,:gw,:n,:mae,:rmse,:sp,:ch,:cp,:ca,:o, now())
                ON CONFLICT (model_version, gw) DO UPDATE SET
                    n_players=:n, mae=:mae, rmse=:rmse, spearman=:sp,
                    captain_hit=:ch, captain_predicted_pts=:cp,
                    captain_actual_pts=:ca, oracle_pts=:o, computed_at=now()
            """), dict(mv=row["model_version"], gw=row["gw"],
                        n=row["n_players"], mae=row["mae"], rmse=row["rmse"],
                        sp=row["spearman"], ch=row["captain_hit"],
                        cp=row["captain_predicted_pts"],
                        ca=row["captain_actual_pts"], o=row["oracle_pts"]))
            session.commit()
            results.append(row)
    finally:
        session.close()

    _log("=" * 40)
    if results:
        _log(f"DONE. {len(results)} GW(s) scored.")
        _log(f"Mean MAE: {np.mean([r['mae'] for r in results]):.3f}")
        _log(f"Mean Spearman: {np.mean([r['spearman'] for r in results]):.3f}")
        _log(f"Captain hit rate: "
             f"{100 * np.mean([r['captain_hit'] for r in results]):.0f}%")
    else:
        _log("No GWs scored. Check that player_gw_points and predictions "
             "both have rows for the target GW range.")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-gw", type=int, required=True)
    parser.add_argument("--end-gw", type=int, required=True)
    parser.add_argument("--rerun", action="store_true",
                         help="Re-run predictions first (slow; use when the "
                              "model has changed since predictions were made).")
    args = parser.parse_args()
    run_backtest(args.start_gw, args.end_gw, rerun_predictions=args.rerun)