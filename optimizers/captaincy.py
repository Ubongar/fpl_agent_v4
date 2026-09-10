"""Ranks captaincy choices using the probability distribution, not just mean xP --
rewards high ceiling (p90) and start certainty, penalizes volatility for the armband."""


def rank_captains(candidates: list[dict]) -> list[dict]:
    """candidates: [{name, xp_mean, p10, p50, p90, start_prob}]

    Captaincy score: weight ceiling heavily since captaincy doubles the upside,
    but discount by start uncertainty (benched captain = disaster).
    """
    scored = []
    for c in candidates:
        score = (
            0.4 * float(c["xp_mean"])
            + 0.4 * float(c["p90"])
            + 0.2 * float(c["p10"])
        ) * float(c["start_prob"])
        scored.append({**c, "captaincy_score": round(score, 2)})
    return sorted(scored, key=lambda r: r["captaincy_score"], reverse=True)