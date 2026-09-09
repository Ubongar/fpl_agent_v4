"""Walk-forward backtest: for each historical GW, train/derive features using
ONLY data available before that GW, predict, then compare to actual points.
Prevents future leakage -- the #1 bug in naive FPL prediction tools."""
import numpy as np

def walk_forward_backtest(gw_range, predict_fn, actuals_fn):
    """predict_fn(gw) -> dict[player_id, xp]; actuals_fn(gw) -> dict[player_id, actual_pts]
    Both must only look at data known strictly before `gw`."""
    rows = []
    for gw in gw_range:
        preds = predict_fn(gw)
        actuals = actuals_fn(gw)
        for pid, xp in preds.items():
            if pid in actuals:
                rows.append((gw, pid, xp, actuals[pid]))
    if not rows:
        return {"mae": None, "rmse": None, "n": 0}
    errs = np.array([xp - actual for _, _, xp, actual in rows])
    return {
        "mae": round(float(np.mean(np.abs(errs))), 3),
        "rmse": round(float(np.sqrt(np.mean(errs ** 2))), 3),
        "n": len(rows),
        "per_gw_rows": rows,
    }
