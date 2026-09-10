"""Reconstructs per-GW features for past gameweeks using FPL's element-summary
"history" endpoint. Unlike bootstrap-static, each row in this endpoint's
history list IS genuinely per-fixture/per-GW already -- no diffing needed here.

BUG FIX (v4): the original ON CONFLICT DO NOTHING referenced no real unique
constraint, so re-running backfill silently duplicated every row. Fixed by
writing to player_gw_points, which now has a real UNIQUE(player_id, gw)
constraint (see db/schema.sql), and using DO UPDATE so reruns correct
existing rows instead of duplicating or silently no-op'ing on conflict.
"""
import requests
from config import FPL_BASE
from db.connection import get_session
from sqlalchemy import text

def fetch_player_history(player_id: int):
    r = requests.get(f"{FPL_BASE}/element-summary/{player_id}/", timeout=15)
    r.raise_for_status()
    return r.json()["history"]  # each row is genuinely per-GW; "total_points" here is the GW score

def backfill_all(player_ids):
    session = get_session()
    inserted = 0
    for pid in player_ids:
        for gw_row in fetch_player_history(pid):
            session.execute(text("""
                INSERT INTO player_gw_points
                    (player_id, gw, gw_points, minutes, goals_scored, assists, ict_index,
                     expected_goals, expected_assists, now_cost, source)
                VALUES (:pid, :gw, :pts, :min, :g, :a, :ict, :xg, :xa, :cost, 'backfill')
                ON CONFLICT (player_id, gw) DO UPDATE SET
                    gw_points = EXCLUDED.gw_points, minutes = EXCLUDED.minutes,
                    goals_scored = EXCLUDED.goals_scored, assists = EXCLUDED.assists,
                    ict_index = EXCLUDED.ict_index, expected_goals = EXCLUDED.expected_goals,
                    expected_assists = EXCLUDED.expected_assists, now_cost = EXCLUDED.now_cost,
                    source = 'backfill', computed_at = now()
            """), dict(pid=pid, gw=gw_row["round"], pts=gw_row["total_points"],
                        min=gw_row["minutes"], g=gw_row.get("goals_scored", 0),
                        a=gw_row.get("assists", 0), ict=gw_row.get("ict_index"),
                        xg=gw_row.get("expected_goals", 0), xa=gw_row.get("expected_assists", 0),
                        cost=gw_row["value"] / 10))
            inserted += 1
    session.commit()
    session.close()
    return inserted