"""Predicts appearance probability (P(minutes >= 60)) and expected minutes."""
import os
import numpy as np
import joblib

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "artifacts",
                            "expected_minutes_model.joblib")
_cached = None
_load_attempted = False


def _load_trained_model():
    global _cached, _load_attempted
    if not _load_attempted:
        _load_attempted = True
        if os.path.exists(_MODEL_PATH):
            try:
                _cached = joblib.load(_MODEL_PATH)
            except Exception as e:
                print(f"[expected_minutes] Could not load {_MODEL_PATH}: {e!r}")
                _cached = None
    return _cached


def _heuristic_expected_minutes(minutes_history):
    if not minutes_history:
        return {"appearance_prob": 0.5, "expected_minutes": 45.0,
                "source": "no_history_default"}
    weights = np.exp(np.linspace(-1, 0, len(minutes_history)))
    weights /= weights.sum()
    avg_minutes = float(np.dot(minutes_history, weights))
    app_prob = min(0.98, avg_minutes / 75.0)
    return {"appearance_prob": round(app_prob, 3),
            "expected_minutes": round(avg_minutes, 1),
            "source": "heuristic_fallback"}


def expected_minutes(minutes_history, status="a"):
    if status in ("i", "s", "u", "n"):
        return {"appearance_prob": 0.0, "expected_minutes": 0.0,
                "source": "status_override"}
    if not minutes_history:
        return _heuristic_expected_minutes([])

    bundle = _load_trained_model()
    if bundle is None or len(minutes_history) < 2:
        return _heuristic_expected_minutes(minutes_history)

    model, feature_names = bundle["model"], bundle["features"]
    feat = {
        "avg_minutes_last3": float(np.mean(minutes_history[-3:])),
        "avg_minutes_all": float(np.mean(minutes_history)),
        "started_last_gw": 1 if minutes_history[-1] >= 60 else 0,
        "start_rate": float(np.mean([1 if m >= 60 else 0 for m in minutes_history])),
        "n_prior_gws": len(minutes_history),
    }
    import pandas as pd
    X = pd.DataFrame([[feat[f] for f in feature_names]], columns=feature_names)
    app_prob = float(model.predict_proba(X)[0, 1])
    expected_min = app_prob * float(np.mean(minutes_history[-3:]))
    return {"appearance_prob": round(app_prob, 3),
            "expected_minutes": round(expected_min, 1),
            "source": "trained_model"}