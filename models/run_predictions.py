"""Populates the `predictions` table with per-player xP for a given gameweek.

v5 BATCHED: The original version made roughly 3 DB round-trips per player
(~2100 queries for ~700 players). Against a local Postgres that was fine
(~30s); against Neon's cloud endpoint (~100ms RTT) it took 5-10 minutes and
looked hung with no progress output.

This version does 8 queries total:
  1. all players
  2. all statuses
  3. all team ratings
  4. all fixtures in the GW
  5. all minutes histories (one query, grouped in Python)
  6. all player xG/xA sums (one query, grouped in Python)
  7. all team xG totals (one query, grouped in Python)
  8. one batched executemany INSERT for every prediction row

Plus a tqdm progress bar over the Python-side computation so it's visibly
alive on long runs.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from tqdm import tqdm
from db.connection import get_session
from sqlalchemy import text
from models.expected_points import player_expected_points
from models.distributions import sample_points_distribution
from optimizers.dgw_bgw import adjust_for_dgw
from config import GOAL_SHARE_WINDOW, MINUTES_HISTORY_WINDOW

MODEL_VERSION = "v5"

NEUTRAL_RATING = {"attack_home": 1.0, "attack_away": 1.0,
                  "defence_home": 1.0, "defence_away": 1.0}

# Bayesian shrinkage priors (same as before, hoisted to module level)
PRIOR_GOAL_SHARE = {"FWD": 0.35, "MID": 0.20, "DEF": 0.05, "GK": 0.0}
PRIOR_ASSIST_SHARE = {"FWD": 0.15, "MID": 0.25, "DEF": 0.10, "GK": 0.0}
ALPHA = 4.0


# --------------------------------------------------------------------------- #
# Batch loaders — one query each
# --------------------------------------------------------------------------- #
def _load_players(session):
    rows = session.execute(text(
        "SELECT player_id, team_id, position FROM players"
    )).fetchall()
    return [{"pid": r.player_id, "team_id": r.team_id, "pos": r.position}
            for r in rows]


def _load_statuses(session, up_to_gw):
    """Status as of the latest snapshot BEFORE up_to_gw. Players with no
    prior snapshot default to 'a' (available) — we don't know otherwise."""
    rows = session.execute(text("""
        SELECT DISTINCT ON (player_id) player_id, status
        FROM player_snapshots
        WHERE gw < :gw
        ORDER BY player_id, pulled_at DESC
    """), dict(gw=up_to_gw)).fetchall()
    return {r.player_id: r.status for r in rows}


def _load_ratings(session, up_to_gw):
    rows = session.execute(text("""
        SELECT DISTINCT ON (team_id) team_id, attack_home, attack_away,
               defence_home, defence_away
        FROM team_strength WHERE gw <= :gw
        ORDER BY team_id, gw DESC
    """), dict(gw=up_to_gw)).fetchall()
    return {
        r.team_id: {
            "attack_home": float(r.attack_home),
            "attack_away": float(r.attack_away),
            "defence_home": float(r.defence_home),
            "defence_away": float(r.defence_away),
        } for r in rows
    }


def _load_fixtures(session, gw):
    rows = session.execute(text(
        "SELECT fixture_id, home_team_id, away_team_id FROM fixtures WHERE gw = :gw"
    ), dict(gw=gw)).fetchall()
    by_team = {}
    for r in rows:
        by_team.setdefault(r.home_team_id, []).append((r, True))
        by_team.setdefault(r.away_team_id, []).append((r, False))
    return by_team


def _load_minutes_histories(session, up_to_gw, window):
    """One query: minutes history for EVERY player. Returns
    {player_id: [minutes ascending, truncated to last `window`]}."""
    rows = session.execute(text("""
        SELECT player_id, gw, minutes
        FROM player_gw_points
        WHERE gw <= :gw AND minutes IS NOT NULL
        ORDER BY player_id, gw
    """), dict(gw=up_to_gw)).fetchall()
    by_player = {}
    for r in rows:
        by_player.setdefault(r.player_id, []).append(r.minutes)
    return {pid: mins[-window:] for pid, mins in by_player.items()}


def _load_player_xgxa(session, up_to_gw, window):
    """One query: sum(xG), sum(xA) per player over the last `window` GWs."""
    rows = session.execute(text("""
        SELECT player_id,
               COALESCE(SUM(expected_goals), 0) AS xg,
               COALESCE(SUM(expected_assists), 0) AS xa
        FROM (
            SELECT player_id, expected_goals, expected_assists,
                   ROW_NUMBER() OVER (PARTITION BY player_id
                                      ORDER BY gw DESC) AS rn
            FROM player_gw_points
            WHERE gw <= :gw
        ) sub
        WHERE rn <= :w
        GROUP BY player_id
    """), dict(gw=up_to_gw, w=window)).fetchall()
    return {r.player_id: (float(r.xg), float(r.xa)) for r in rows}


def _load_team_xg(session, up_to_gw, window):
    """One query: sum(xG) per team over the last `window` GWs."""
    rows = session.execute(text("""
        SELECT p.team_id,
               COALESCE(SUM(pgw.expected_goals), 0) AS team_xg
        FROM player_gw_points pgw
        JOIN players p ON p.player_id = pgw.player_id
        WHERE pgw.gw <= :gw AND pgw.gw > :gw - :w
        GROUP BY p.team_id
    """), dict(gw=up_to_gw, w=window)).fetchall()
    return {r.team_id: float(r.team_xg) for r in rows}


# --------------------------------------------------------------------------- #
# Pure Python helper
# --------------------------------------------------------------------------- #
def _share_from_aggregates(player_xg, player_xa, team_xg, position):
    """Bayesian-shrunk goal/assist shares. Same math as the original
    per-player version, just fed from pre-aggregated batch totals."""
    pg = PRIOR_GOAL_SHARE.get(position, 0.0)
    pa = PRIOR_ASSIST_SHARE.get(position, 0.0)
    adj_g = (player_xg + ALPHA * pg) / (team_xg + ALPHA)
    adj_a = (player_xa + ALPHA * pa) / (team_xg + ALPHA)
    return adj_g, adj_a


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def run_predictions(gw: int) -> int:
    session = get_session()
    try:
        # ---- 7 batch loads ----
        print(f"[run_predictions] gw{gw}: loading reference data…")
        players = _load_players(session)
        statuses = _load_statuses(session, gw)
        ratings = _load_ratings(session, gw - 1)
        fixtures_by_team = _load_fixtures(session, gw)
        minutes_by_player = _load_minutes_histories(
            session, gw - 1, MINUTES_HISTORY_WINDOW)
        xgxa_by_player = _load_player_xgxa(session, gw - 1, GOAL_SHARE_WINDOW)
        team_xg_by_team = _load_team_xg(session, gw - 1, GOAL_SHARE_WINDOW)
        n_legs = sum(len(v) for v in fixtures_by_team.values())
        print(f"[run_predictions] gw{gw}: loaded {len(players)} players, "
              f"{n_legs} fixture-legs, {len(ratings)} team ratings.")

        # ---- Python-side computation ----
        rows_to_write = []
        injured_rows = 0
        skipped_bgw = 0
        normal_rows = 0

        for p in tqdm(players, desc=f"Computing xP (GW{gw})", unit="player"):
            pid = p["pid"]
            team_id = p["team_id"]
            position = p["pos"]
            status = statuses.get(pid, "a")

            # Injured / suspended / unavailable → explicit zero row
            if status in ("i", "s", "u", "n"):
                rows_to_write.append(dict(
                    pid=pid, gw=gw, mv=MODEL_VERSION,
                    xm=0.0, p10=0.0, p50=0.0, p90=0.0, sp=0.0, xc=0.0,
                ))
                injured_rows += 1
                continue

            legs = fixtures_by_team.get(team_id, [])
            if not legs:
                skipped_bgw += 1
                continue

            minutes_hist = minutes_by_player.get(pid, [])
            player_xg, player_xa = xgxa_by_player.get(pid, (0.0, 0.0))
            team_xg = team_xg_by_team.get(team_id, 0.0)
            goal_share, assist_share = _share_from_aggregates(
                player_xg, player_xa, team_xg, position)

            leg_xps, start_probs = [], []
            for fixture, is_home in legs:
                opp_id = fixture.away_team_id if is_home else fixture.home_team_id
                team_r = ratings.get(team_id, NEUTRAL_RATING)
                opp_r = ratings.get(opp_id, NEUTRAL_RATING)

                team_attack = (team_r["attack_home"] if is_home
                               else team_r["attack_away"])
                team_defence = (team_r["defence_home"] if is_home
                                else team_r["defence_away"])
                opp_attack = (opp_r["attack_away"] if is_home
                              else opp_r["attack_home"])
                opp_defence = (opp_r["defence_away"] if is_home
                               else opp_r["defence_home"])

                result = player_expected_points(
                    position=position, minutes_history=minutes_hist,
                    status=status, team_attack=team_attack,
                    opp_defence=opp_defence, opp_attack=opp_attack,
                    team_defence=team_defence, player_goal_share=goal_share,
                    player_assist_share=assist_share, is_home=is_home,
                )
                leg_xps.append(result["xp_conditional"])
                start_probs.append(result["start_prob"])

            summed_conditional = adjust_for_dgw({pid: leg_xps})[pid]
            avg_start_prob = round(sum(start_probs) / len(start_probs), 3)
            dist = sample_points_distribution(summed_conditional, avg_start_prob)

            rows_to_write.append(dict(
                pid=pid, gw=gw, mv=MODEL_VERSION,
                xm=round(dist["mean"], 2),
                p10=dist["p10"], p50=dist["p50"], p90=dist["p90"],
                sp=avg_start_prob, xc=summed_conditional,
            ))
            normal_rows += 1

        # ---- One batched upsert ----
        print(f"[run_predictions] gw{gw}: writing {len(rows_to_write)} rows "
              f"in one batch…")
        if rows_to_write:
            session.execute(text("""
                INSERT INTO predictions
                    (player_id, gw, model_version, xp_mean, xp_p10, xp_p50,
                     xp_p90, start_prob, xp_conditional)
                VALUES (:pid, :gw, :mv, :xm, :p10, :p50, :p90, :sp, :xc)
                ON CONFLICT (player_id, gw, model_version) DO UPDATE SET
                    xp_mean = EXCLUDED.xp_mean,
                    xp_p10  = EXCLUDED.xp_p10,
                    xp_p50  = EXCLUDED.xp_p50,
                    xp_p90  = EXCLUDED.xp_p90,
                    start_prob = EXCLUDED.start_prob,
                    xp_conditional = EXCLUDED.xp_conditional,
                    created_at = now()
            """), rows_to_write)
            session.commit()

        print(f"[run_predictions] gw{gw}: done. "
              f"{len(rows_to_write)} written "
              f"({injured_rows} injured, {skipped_bgw} BGW, "
              f"{normal_rows} normal).")
        return len(rows_to_write)
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, required=True)
    args = parser.parse_args()
    run_predictions(args.gw)