"""Trains a REAL logistic regression on your actual player_gw_points history,
replacing the naive recency-weighted heuristic that calibration flagged as
systematically too pessimistic. Run this once you have several gameweeks of
real data, then re-run periodically as more gameweeks accumulate.

Usage:
    python -m models.train_expected_minutes

Saves the fitted model to models/artifacts/expected_minutes_model.joblib
-- expected_minutes.py automatically loads it if present, and falls back to
the old heuristic only if no trained model exists yet (e.g. brand new setup).
"""
import os
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import brier_score_loss
import joblib

from db.connection import get_session
from sqlalchemy import text

ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "artifacts")
MODEL_PATH = os.path.join(ARTIFACT_DIR, "expected_minutes_model.joblib")


def build_training_data() -> pd.DataFrame:
    """For every player, at every gw >= 3, build features from their PRIOR
    gameweeks only (no lookahead) and the label = did they start this gw."""
    session = get_session()
    rows = session.execute(text("""
        SELECT player_id, gw, minutes FROM player_gw_points ORDER BY player_id, gw
    """)).fetchall()
    session.close()

    by_player = {}
    for r in rows:
        by_player.setdefault(r.player_id, []).append((r.gw, r.minutes))

    records = []
    for pid, history in by_player.items():
        history.sort()
        minutes_seq = [m for _, m in history]
        for i in range(2, len(minutes_seq)):  # need >=2 prior GWs as features
            prior = minutes_seq[:i]
            label = 1 if minutes_seq[i] > 0 else 0
            records.append({
                "player_id": pid,
                "avg_minutes_last3": float(np.mean(prior[-3:])),
                "avg_minutes_all": float(np.mean(prior)),
                "started_last_gw": 1 if prior[-1] > 0 else 0,
                "start_rate": float(np.mean([1 if m > 0 else 0 for m in prior])),
                "n_prior_gws": len(prior),
                "label": label,
            })
    return pd.DataFrame(records)


def train_and_save():
    df = build_training_data()
    if len(df) < 30:
        print(f"Only {len(df)} training rows available -- need more gameweeks "
              f"of history before a trained model will be reliable. Skipping "
              f"training; expected_minutes.py will keep using the heuristic.")
        return None

    features = ["avg_minutes_last3", "avg_minutes_all", "started_last_gw", "start_rate", "n_prior_gws"]
    X, y = df[features], df["label"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    model = LogisticRegression(max_iter=1000)
    model.fit(X_train, y_train)

    test_probs = model.predict_proba(X_test)[:, 1]
    brier = brier_score_loss(y_test, test_probs)  # lower = better calibrated, 0.25 = coin-flip-bad baseline
    print(f"Trained on {len(X_train)} rows, tested on {len(X_test)} rows.")
    print(f"Brier score on held-out test set: {brier:.4f} (lower is better; naive baseline ~0.25)")

    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    joblib.dump({"model": model, "features": features}, MODEL_PATH)
    print(f"Saved trained model to {MODEL_PATH}")
    return model


if __name__ == "__main__":
    train_and_save()
