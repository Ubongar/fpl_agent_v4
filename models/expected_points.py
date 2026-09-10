"""Expected points per player, CONDITIONAL on the player appearing.
Multiply by start_prob only if you need the unconditional value."""
from models.expected_minutes import expected_minutes
from models.dixon_coles import score_matrix, clean_sheet_prob, expected_goals

FPL_APPEARANCE_PTS = 2
CS_PTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
GOAL_PTS = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
ASSIST_PTS = 3


def player_expected_points(position, minutes_history, status,
                            team_attack, opp_defence, opp_attack, team_defence,
                            player_goal_share, player_assist_share, is_home):
    mins = expected_minutes(minutes_history, status)

    if is_home:
        matrix = score_matrix(team_attack, opp_defence, opp_attack, team_defence)
        team_xg, opp_xg = expected_goals(matrix)
        cs_prob = clean_sheet_prob(matrix, "home")
    else:
        matrix = score_matrix(opp_attack, team_defence, team_attack, opp_defence)
        opp_xg, team_xg = expected_goals(matrix)
        cs_prob = clean_sheet_prob(matrix, "away")

    xp = float(FPL_APPEARANCE_PTS)
    xp += cs_prob * CS_PTS.get(position, 0)
    xp += team_xg * float(player_goal_share) * GOAL_PTS.get(position, 4)
    xp += team_xg * float(player_assist_share) * ASSIST_PTS

    return {
        "xp_conditional": round(xp, 2),
        "start_prob": float(mins["start_prob"]) if "start_prob" in mins
                       else float(mins["appearance_prob"]),
        "team_xg": round(float(team_xg), 2),
        "cs_prob": round(float(cs_prob), 3),
    }