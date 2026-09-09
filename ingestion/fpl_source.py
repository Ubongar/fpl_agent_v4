"""Official FPL API ingestion -> immutable snapshots + derived per-GW points.

BUG FIX (v4): bootstrap-static's "total_points" is a SEASON-CUMULATIVE total,
not a per-gameweek score. v3 stored it directly as if it were per-GW, which
would have silently corrupted any rolling_form calculation built on top of it.
Fixed by: (1) storing it under the honestly-named `season_total_points` column
in the immutable player_snapshots log, and (2) deriving true per-GW points via
compute_gw_points_from_snapshots(), which diffs consecutive cumulative totals
and writes the result to player_gw_points -- the ONLY table models should read
per-GW figures from.
"""
import requests
from datetime import datetime
from config import FPL_BASE
from db.connection import get_session
from sqlalchemy import text

def fetch_bootstrap():
    r = requests.get(f"{FPL_BASE}/bootstrap-static/", timeout=15)
    r.raise_for_status()
    return r.json()

def fetch_fixtures():
    r = requests.get(f"{FPL_BASE}/fixtures/", timeout=15)
    r.raise_for_status()
    return r.json()

def upsert_teams_and_players(data):
    session = get_session()
    for t in data["teams"]:
        session.execute(text(
            "INSERT INTO teams (team_id, name, short_name) VALUES (:id,:n,:s) "
            "ON CONFLICT (team_id) DO UPDATE SET name=:n, short_name=:s"
        ), dict(id=t["id"], n=t["name"], s=t["short_name"]))
    pos_map = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    for p in data["elements"]:
        session.execute(text(
            "INSERT INTO players (player_id, web_name, team_id, position, now_cost) "
            "VALUES (:id,:w,:t,:p,:c) ON CONFLICT (player_id) DO UPDATE SET "
            "team_id=:t, position=:p, now_cost=:c"
        ), dict(id=p["id"], w=p["web_name"], t=p["team"], p=pos_map.get(p["element_type"]), c=p["now_cost"]/10))
    session.commit()
    session.close()

def snapshot_players(data, gw):
    """Insert one immutable row per player for this pull. `season_total_points`
    is explicitly cumulative -- do NOT treat it as this gameweek's score."""
    session = get_session()
    for p in data["elements"]:
        session.execute(text(
            "INSERT INTO player_snapshots (player_id, pulled_at, gw, minutes, "
            "season_total_points, form, selected_by_percent, ict_index, "
            "expected_goals, expected_assists, expected_goals_conceded, now_cost, "
            "status, news) VALUES "
            "(:pid,:t,:gw,:min,:season_pts,:form,:sel,:ict,:xg,:xa,:xgc,:cost,:status,:news)"
        ), dict(pid=p["id"], t=datetime.utcnow(), gw=gw, min=p["minutes"],
                season_pts=p["total_points"], form=p["form"], sel=p["selected_by_percent"],
                ict=p["ict_index"], xg=p.get("expected_goals", 0), xa=p.get("expected_assists", 0),
                xgc=p.get("expected_goals_conceded", 0), cost=p["now_cost"]/10,
                status=p["status"], news=p.get("news", "")))
    session.commit()
    session.close()

def compute_gw_points_from_snapshots(gw: int):
    """Derives TRUE per-GW points by diffing this GW's cumulative season total
    against the most recent prior snapshot's cumulative total, per player.
    Idempotent: ON CONFLICT (player_id, gw) DO UPDATE relies on the real
    UNIQUE(player_id, gw) constraint on player_gw_points (bug fix #2) -- so
    re-running this for the same gw after re-ingesting corrects the row
    instead of duplicating it."""
    session = get_session()
    rows = session.execute(text("""
        WITH ranked AS (
            SELECT player_id, gw, season_total_points, minutes, ict_index,
                   expected_goals, expected_assists, now_cost,
                   ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY pulled_at DESC) AS rn
            FROM player_snapshots WHERE gw <= :gw
        ),
        current AS (SELECT * FROM ranked WHERE gw = :gw AND rn = 1),
        previous AS (
            SELECT DISTINCT ON (player_id) player_id, season_total_points AS prev_total
            FROM ranked WHERE gw < :gw ORDER BY player_id, gw DESC
        )
        SELECT c.player_id, c.season_total_points - COALESCE(p.prev_total, 0) AS gw_points,
               c.minutes, c.ict_index, c.expected_goals, c.expected_assists, c.now_cost
        FROM current c LEFT JOIN previous p ON p.player_id = c.player_id
    """), dict(gw=gw)).fetchall()

    for r in rows:
        session.execute(text("""
            INSERT INTO player_gw_points
                (player_id, gw, gw_points, minutes, ict_index, expected_goals, expected_assists, now_cost, source)
            VALUES (:pid, :gw, :pts, :min, :ict, :xg, :xa, :cost, 'snapshot_diff')
            ON CONFLICT (player_id, gw) DO UPDATE SET
                gw_points = EXCLUDED.gw_points, minutes = EXCLUDED.minutes,
                ict_index = EXCLUDED.ict_index, expected_goals = EXCLUDED.expected_goals,
                expected_assists = EXCLUDED.expected_assists, now_cost = EXCLUDED.now_cost,
                source = 'snapshot_diff', computed_at = now()
        """), dict(pid=r.player_id, gw=gw, pts=r.gw_points, min=r.minutes, ict=r.ict_index,
                    xg=r.expected_goals, xa=r.expected_assists, cost=r.now_cost))
    session.commit()
    session.close()
    return len(rows)

def run_daily_ingest(gw):
    data = fetch_bootstrap()
    upsert_teams_and_players(data)
    snapshot_players(data, gw)
    if gw > 1:
        compute_gw_points_from_snapshots(gw)
    return len(data["elements"])
