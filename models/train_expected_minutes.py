"""Trains logistic regression on player_gw_points history.
Target = P(minutes >= 60), the true "start" label."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    session = get_session()
    rows = session.execute(text("""
        SELECT player_id, gw, minutes FROM player_gw_points
        WHERE minutes IS NOT NULL ORDER BY player_id, gw
    """)).fetchall()
    session.close()

    by_player = {}
    for r in rows:
        by_player.setdefault(r.player_id, []).append((r.gw, r.minutes))

    records = []
    for pid, history in by_player.items():
        history.sort()
        minutes_seq = [m for _, m in history]
        for i in range(2, len(minutes_seq)):
            prior = minutes_seq[:i]
            label = 1 if minutes_seq[i] >= 60 else 0
            records.append({
                "player_id": pid,
                "avg_minutes_last3": float(np.mean(prior[-3:])),
                "avg_minutes_all": float(np.mean(prior)),
                "started_last_gw": 1 if prior[-1] >= 60 else 0,
                "start_rate": float(np.mean([1 if m >= 60 else 0 for m in prior])),
                "n_prior_gws": len(prior),
                "label": label,
            })
    return pd.DataFrame(records)


def train_and_save():
    df = build_training_data()
    if len(df) < 30:
        print(f"[train_expected_minutes] Only {len(df)} rows — need >=30. Skipping.")
        return None

    features = ["avg_minutes_last3", "avg_minutes_all", "started_last_gw",
                "start_rate", "n_prior_gws"]
    X, y = df[features], df["label"]

    if y.nunique() < 2:
        print("[train_expected_minutes] Only one class present — cannot fit.")
        return None

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y)

    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(X_train, y_train)

    probs = model.predict_proba(X_test)[:, 1]
    brier = brier_score_loss(y_test, probs)
    print(f"[train_expected_minutes] Trained on {len(X_train)}, tested on {len(X_test)}.")
    print(f"[train_expected_minutes] Brier = {brier:.4f} (lower is better).")

    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    joblib.dump({"model": model, "features": features}, MODEL_PATH)
    print(f"[train_expected_minutes] Saved → {MODEL_PATH}")
    return model


if __name__ == "__main__":
    train_and_save()