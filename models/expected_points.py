"""Combines expected_minutes + dixon_coles team goal expectation + player-level
attacking share into a single expected-points estimate. This is the model
every optimizer downstream consumes."""
from models.expected_minutes import expected_minutes
from models.dixon_coles import score_matrix, clean_sheet_prob, expected_goals

FPL_APPEARANCE_PTS = 2
CS_PTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
GOAL_PTS = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
ASSIST_PTS = 3

def player_expected_points(position: str, minutes_history: list[int], status: str,
                            team_attack, opp_defence, opp_attack, team_defence,
                            player_goal_share: float, player_assist_share: float,
                            is_home: bool) -> dict:
    mins = expected_minutes(minutes_history, status)
    if is_home:
        matrix = score_matrix(team_attack, opp_defence, opp_attack, team_defence)
        team_xg, opp_xg = expected_goals(matrix)
        cs_prob = clean_sheet_prob(matrix, "home")
    else:
        matrix = score_matrix(opp_attack, team_defence, team_attack, opp_defence)
        opp_xg, team_xg = expected_goals(matrix)
        cs_prob = clean_sheet_prob(matrix, "away")

    p_start = mins["start_prob"]
    xp = p_start * FPL_APPEARANCE_PTS
    xp += p_start * cs_prob * CS_PTS.get(position, 0)
    xp += p_start * team_xg * player_goal_share * GOAL_PTS.get(position, 4)
    xp += p_start * team_xg * player_assist_share * ASSIST_PTS
    return {"xp_mean": round(xp, 2), "start_prob": p_start, "team_xg": round(team_xg, 2), "cs_prob": round(cs_prob, 3)}
