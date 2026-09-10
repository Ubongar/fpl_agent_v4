"""Ranks captaincy choices. v5: since predictions.xp_mean is now the
UNCONDITIONAL expected value (start_prob already baked in via the simulation),
this module no longer multiplies by start_prob again.

v5.1: goalkeepers are excluded. GKs have a bounded scoring ceiling (no goals,
rarely assists, penalty saves are the only outsized return) that the Gamma-based
distribution doesn't model correctly, so their simulated p90 is inflated and
they'd otherwise appear in the top 5 captains. Real FPL managers never captain
a GK; this now matches that reality."""


def rank_captains(candidates: list[dict]) -> list[dict]:
    """candidates: [{name, pos, xp_mean, p10, p50, p90, start_prob}].
    Returns same list with 'captaincy_score' added, sorted descending."""
    scored = []
    for c in candidates:
        if c.get("pos") == "GK":
            continue  # never captain a goalkeeper
        xp = float(c["xp_mean"])
        p10 = float(c.get("p10") or 0.0)
        p90 = float(c.get("p90") or 0.0)
        score = 0.4 * xp + 0.4 * p90 + 0.2 * p10
        scored.append({**c, "captaincy_score": round(score, 2)})
    return sorted(scored, key=lambda r: r["captaincy_score"], reverse=True)