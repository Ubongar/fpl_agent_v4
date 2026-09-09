"""Ranks captaincy choices using the probability distribution, not just mean xP --
rewards high ceiling (p90) and start certainty, penalizes volatility for the armband."""

def rank_captains(candidates: list[dict]) -> list[dict]:
    """candidates: [{name, xp_mean, p10, p50, p90, start_prob}]"""
    scored = []
    for c in candidates:
        # Captaincy score: weight ceiling heavily since captaincy doubles the upside,
        # but discount by start uncertainty (benched captain = disaster).
        score = (0.4 * c["xp_mean"] + 0.4 * c["p90"] + 0.2 * c["p10"]) * c["start_prob"]
        scored.append({**c, "captaincy_score": round(score, 2)})
    return sorted(scored, key=lambda r: r["captaincy_score"], reverse=True)
