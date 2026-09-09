"""Rolling attack/defence ratings per team, split home/away, updated per GW.
Uses a simple exponentially-weighted goals-for/against ratio vs league average --
sufficient as Dixon-Coles input. Swap for a proper Poisson GLM with more history."""
import numpy as np

LEAGUE_AVG_GOALS = 1.4  # rough Premier League long-run average goals/team/game

def update_team_strength(goals_for_history: list[int], goals_against_history: list[int],
                          decay: float = 0.85) -> dict:
    if not goals_for_history:
        return {"attack": 1.0, "defence": 1.0}
    weights = decay ** np.arange(len(goals_for_history))[::-1]
    weights /= weights.sum()
    attack = float(np.dot(goals_for_history, weights)) / LEAGUE_AVG_GOALS
    defence = float(np.dot(goals_against_history, weights)) / LEAGUE_AVG_GOALS
    return {"attack": round(attack, 3), "defence": round(defence, 3)}
