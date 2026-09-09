"""Monte Carlo sampling around the point estimate -> probability distribution.
Optimizers use this for risk-aware decisions (e.g. captaincy ceiling/floor),
not just the mean."""
import numpy as np

def sample_points_distribution(xp_mean: float, start_prob: float, n_sims: int = 5000, seed=None) -> dict:
    rng = np.random.default_rng(seed)
    plays = rng.random(n_sims) < start_prob
    # Points ~ Gamma to allow right-skew (explosive hauls) while keeping mean anchored
    shape = 2.0
    scale = max(xp_mean, 0.1) / shape
    raw = rng.gamma(shape, scale, n_sims)
    samples = np.where(plays, raw, 0.0)
    return {
        "p10": float(np.percentile(samples, 10)),
        "p50": float(np.percentile(samples, 50)),
        "p90": float(np.percentile(samples, 90)),
        "mean": float(samples.mean()),
        "ceiling_prob_10plus": float((samples >= 10).mean()),
    }
