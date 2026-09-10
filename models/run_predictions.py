"""Populates the `predictions` table with real per-player xP for a given
gameweek. This is the piece that was missing entirely: predictions existed in
schema.sql but nothing wrote to it, so every optimizer downstream had no real
data to consume.

Pipeline per player: real fixture(s) for gw -> real team_strength ratings ->
dixon_coles -> expected_points -> distributions, with DGW legs summed via
dgw_bgw.adjust_for_dgw and BGW players skipped entirely (no fixture = no
prediction row, not a fabricated 0).

Usage:
    python -m models.run_predictions --gw N
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from db.connection import get_session
from sqlalchemy import text
from models.expected_points import player_expected_points
from models.distributions import sample_points_distribution
from optimizers.dgw_bgw import adjust_for_dgw
from models.train_team_strength import get_latest_ratings

MODEL_VERSION = "v4"
GOAL_SHARE_WINDOW = 6  # gameweeks of real goals/assists used to estimate a player's share of team goals


def _minutes_history(session, player_id, up_to_gw, window=10):
    rows = session.execute(text(
        "SELECT minutes FROM player_gw_points WHERE player_id=:p AND gw <= :gw "
        "ORDER BY gw DESC LIMIT :w"), dict(p=player_id, gw=up_to_gw, w=window)).fetchall()
    return [r.minutes for r in rows][::-1]


# Create an empty dictionary above the function to store the cached team data
_team_xg_cache = {}

def _team_expected_goals(session, team_id, up_to_gw, window=GOAL_SHARE_WINDOW):
    """Calculates the team's total expected goals (xG) over the rolling window 
    by summing the xG of all players on that team, utilizing an in-memory cache."""
    
    # 1. Define a unique signature for this specific query
    cache_key = (team_id, up_to_gw, window)
    
    # 2. Check the cache before hitting PostgreSQL
    if cache_key in _team_xg_cache:
        return _team_xg_cache[cache_key]
        
    # 3. If not in cache, run the expensive query
    row = session.execute(text("""
        SELECT COALESCE(SUM(pgw.expected_goals), 0) AS team_xg
        FROM player_gw_points pgw
        JOIN players p ON p.player_id = pgw.player_id
        WHERE p.team_id = :t 
          AND pgw.gw <= :gw 
          AND pgw.gw > :gw - :w
    """), dict(t=team_id, gw=up_to_gw, w=window)).fetchone()
    
    # 4. Save the result to the cache for the next player on this team
    _team_xg_cache[cache_key] = float(row.team_xg)
    
    return _team_xg_cache[cache_key]


def _player_xg_xa_share(session, player_id, team_id, position, up_to_gw, window=GOAL_SHARE_WINDOW):
    """Calculates the player's share of team xG and xA, regularized with a 
    Bayesian prior based on their position to handle early-season small sample sizes."""
    
    # 1. Fetch the player's accumulated xG and xA
    row = session.execute(text("""
        SELECT COALESCE(SUM(expected_goals),0) AS xg, COALESCE(SUM(expected_assists),0) AS xa 
        FROM (
            SELECT expected_goals, expected_assists 
            FROM player_gw_points 
            WHERE player_id=:p AND gw <= :gw 
            ORDER BY gw DESC 
            LIMIT :w
        ) AS recent_gws
    """), dict(p=player_id, gw=up_to_gw, w=window)).fetchone()
    
    player_xg = float(row.xg)
    player_xa = float(row.xa)
    
    # 2. Fetch the team's accumulated xG
    team_xg = _team_expected_goals(session, team_id, up_to_gw, window)
    
    # 3. Define the Positional Priors
    PRIOR_GOAL_SHARE = {"FWD": 0.35, "MID": 0.20, "DEF": 0.05, "GK": 0.0}
    PRIOR_ASSIST_SHARE = {"FWD": 0.15, "MID": 0.25, "DEF": 0.10, "GK": 0.0}
    ALPHA = 4.0  # The shrinkage weight (acts as ~3 matches of underlying team xG)
    
    prior_g = PRIOR_GOAL_SHARE.get(position, 0.0)
    prior_a = PRIOR_ASSIST_SHARE.get(position, 0.0)
    
    # 4. Apply Bayesian Shrinkage Formula
    adjusted_goal_share = (player_xg + (ALPHA * prior_g)) / (team_xg + ALPHA)
    adjusted_assist_share = (player_xa + (ALPHA * prior_a)) / (team_xg + ALPHA)
    
    return adjusted_goal_share, adjusted_assist_share


def run_predictions(gw: int):
    session = get_session()
    players = session.execute(text("SELECT player_id, team_id, position FROM players")).fetchall()
    status_rows = session.execute(text(
        "SELECT DISTINCT ON (player_id) player_id, status FROM player_snapshots "
        "ORDER BY player_id, pulled_at DESC")).fetchall()
    status_map = {r.player_id: r.status for r in status_rows}

    fixture_rows = session.execute(text("SELECT * FROM fixtures WHERE gw=:gw"), dict(gw=gw)).fetchall()
    fixtures_by_team = {}
    for f in fixture_rows:
        fixtures_by_team.setdefault(f.home_team_id, []).append((f, True))
        fixtures_by_team.setdefault(f.away_team_id, []).append((f, False))

    written, skipped_bgw = 0, 0
    for p in players:
        legs = fixtures_by_team.get(p.team_id, [])
        if not legs:
            skipped_bgw += 1
            continue  # real BGW -- no prediction row, not a fabricated 0

        minutes_hist = _minutes_history(session, p.player_id, gw - 1)
        goal_share, assist_share = _player_xg_xa_share(session, p.player_id, p.team_id, p.position, gw - 1)
        status = status_map.get(p.player_id, "a")

        leg_xps, start_probs = [], []
        for fixture, is_home in legs:
            opp_id = fixture.away_team_id if is_home else fixture.home_team_id
            team_r = get_latest_ratings(session, p.team_id, gw - 1)
            opp_r = get_latest_ratings(session, opp_id, gw - 1)
            team_attack = team_r["attack_home"] if is_home else team_r["attack_away"]
            team_defence = team_r["defence_home"] if is_home else team_r["defence_away"]
            opp_attack = opp_r["attack_away"] if is_home else opp_r["attack_home"]
            opp_defence = opp_r["defence_away"] if is_home else opp_r["defence_home"]

            result = player_expected_points(
                position=p.position, minutes_history=minutes_hist, status=status,
                team_attack=team_attack, opp_defence=opp_defence,
                opp_attack=opp_attack, team_defence=team_defence,
                player_goal_share=goal_share, player_assist_share=assist_share,
                is_home=is_home,
            )
            leg_xps.append(result["xp_mean"])
            start_probs.append(result["start_prob"])

        summed_xp = adjust_for_dgw({p.player_id: leg_xps})[p.player_id]
        avg_start_prob = round(sum(start_probs) / len(start_probs), 3)
        dist = sample_points_distribution(summed_xp, avg_start_prob)

        session.execute(text("""
            INSERT INTO predictions (player_id, gw, model_version, xp_mean, xp_p10, xp_p50, xp_p90, start_prob)
            VALUES (:pid,:gw,:mv,:xm,:p10,:p50,:p90,:sp)
            ON CONFLICT (player_id, gw, model_version) DO UPDATE SET
                xp_mean=:xm, xp_p10=:p10, xp_p50=:p50, xp_p90=:p90, start_prob=:sp, created_at=now()
        """), dict(pid=p.player_id, gw=gw, mv=MODEL_VERSION, xm=summed_xp,
                    p10=dist["p10"], p50=dist["p50"], p90=dist["p90"], sp=avg_start_prob))
        written += 1

    session.commit()
    session.close()
    print(f"Wrote {written} predictions for gw{gw} ({skipped_bgw} skipped -- real BGW, no fixture).")
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, required=True)
    args = parser.parse_args()
    run_predictions(args.gw)