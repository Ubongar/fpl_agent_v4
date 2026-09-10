"""Predicts start probability / expected minutes for a player in gw+1.

v2: loads a REAL logistic regression trained on your actual player_gw_points
history (see train_expected_minutes.py) if one exists. Falls back to the
original recency-weighted heuristic only when no trained model is present yet
(e.g. brand new setup with too little history) -- this fallback is honestly
what calibration flagged as too pessimistic, so train the real model as soon
as you have enough gameweeks.
"""
import os
import numpy as np
import joblib

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "artifacts", "expected_minutes_model.joblib")
_cached = None
_load_attempted = False


def _load_trained_model():
    global _cached, _load_attempted
    if not _load_attempted:
        _load_attempted = True
        if os.path.exists(_MODEL_PATH):
            _cached = joblib.load(_MODEL_PATH)
    return _cached


def _heuristic_expected_minutes(minutes_history: list[int]) -> dict:
    """Original v1 fallback -- kept only for when no trained model exists yet."""
    weights = np.exp(np.linspace(-1, 0, len(minutes_history)))
    weights /= weights.sum()
    avg_minutes = float(np.dot(minutes_history, weights))
    start_prob = min(0.98, avg_minutes / 90.0)
    return {"start_prob": round(start_prob, 3), "expected_minutes": round(avg_minutes, 1), "source": "heuristic_fallback"}


def expected_minutes(minutes_history: list[int], status: str = "a") -> dict:
    if status in ("i", "s", "u"):  # injured / suspended / unavailable
        return {"start_prob": 0.0, "expected_minutes": 0.0, "source": "status_override"}
    if not minutes_history:
        return {"start_prob": 0.5, "expected_minutes": 45.0, "source": "no_history_default"}

    bundle = _load_trained_model()
    if bundle is None or len(minutes_history) < 2:
        return _heuristic_expected_minutes(minutes_history)

    model, feature_names = bundle["model"], bundle["features"]
    feat = {
        "avg_minutes_last3": float(np.mean(minutes_history[-3:])),
        "avg_minutes_all": float(np.mean(minutes_history)),
        "started_last_gw": 1 if minutes_history[-1] > 0 else 0,
        "start_rate": float(np.mean([1 if m > 0 else 0 for m in minutes_history])),
        "n_prior_gws": len(minutes_history),
    }
    import pandas as pd
    X = pd.DataFrame([[feat[f] for f in feature_names]], columns=feature_names)
    start_prob = float(model.predict_proba(X)[0, 1])
    expected_min = start_prob * float(np.mean(minutes_history[-3:]))  # scale recent avg by real P(start)
    return {"start_prob": round(start_prob, 3), "expected_minutes": round(expected_min, 1), "source": "trained_model"}