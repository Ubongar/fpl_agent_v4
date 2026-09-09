"""Checks predicted probabilities match real-world frequency.
E.g. players predicted 'start_prob ~0.7' should actually start ~70% of the time.
Bucket predictions, compare to observed rate, store to model_calibration table."""
import numpy as np

def calibration_curve(predicted_probs: list[float], outcomes: list[int], n_bins: int = 10) -> list[dict]:
    predicted_probs, outcomes = np.array(predicted_probs), np.array(outcomes)
    bins = np.linspace(0, 1, n_bins + 1)
    results = []
    for i in range(n_bins):
        mask = (predicted_probs >= bins[i]) & (predicted_probs < bins[i + 1])
        if mask.sum() == 0:
            continue
        results.append({
            "bucket": f"{bins[i]:.1f}-{bins[i+1]:.1f}",
            "predicted_rate": round(float(predicted_probs[mask].mean()), 3),
            "actual_rate": round(float(outcomes[mask].mean()), 3),
            "n": int(mask.sum()),
        })
    return results

def is_well_calibrated(curve: list[dict], tolerance: float = 0.1) -> bool:
    return all(abs(b["predicted_rate"] - b["actual_rate"]) <= tolerance for b in curve)
