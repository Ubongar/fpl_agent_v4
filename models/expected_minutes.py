"""Predicts start probability / expected minutes for a player in gw+1.
MVP: recency-weighted heuristic on minutes history. Swap in a logistic
regression (features: avg last-5 minutes, days since return from injury,
squad depth at position) once enough historical rows exist in player_snapshots."""
import numpy as np

def expected_minutes(minutes_history: list[int], status: str = "a") -> dict:
    if status in ("i", "s", "u"):  # injured / suspended / unavailable
        return {"start_prob": 0.0, "expected_minutes": 0.0}
    if not minutes_history:
        return {"start_prob": 0.5, "expected_minutes": 45.0}
    weights = np.exp(np.linspace(-1, 0, len(minutes_history)))  # recent games weighted higher
    weights /= weights.sum()
    avg_minutes = float(np.dot(minutes_history, weights))
    start_prob = min(0.98, avg_minutes / 90.0)
    return {"start_prob": round(start_prob, 3), "expected_minutes": round(avg_minutes, 1)}
