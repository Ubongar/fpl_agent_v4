"""Official FPL API ingestion -> snapshots + per-GW points."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
from tqdm import tqdm
from config import FPL_BASE
from db.connection import get_session
from sqlalchemy import text


_http_session = None


def get_http_session():
    global _http_session
    if _http_session is not None:
        return _http_session
    s = requests.Session()
    retry = Retry(total=5, connect=5, read=5, backoff_factor=1.5,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset(["GET"]), raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": "fpl-agent/1.0 (personal research)",
                      "Accept": "application/json"})
    _http_session = s
    return s


def _get_json(path):
    s = get_http_session()
    r = s.get(f"{FPL_BASE}{path}", timeout=(10, 30))
    r.raise_for_status()
    return r.json()


def fetch_bootstrap():
    return _get_json("/bootstrap-static/")


def fetch_fixtures():
    return _get_json("/fixtures/")


def upsert_teams_and_players(data):
    session = get_session()
    for t in tqdm(data["teams"], desc="Upserting teams", unit="team"):
        session.execute(text(
            "INSERT INTO teams (team_id, name, short_name) VALUES (:id,:n,:s) "
            "ON CONFLICT (team_id) DO UPDATE SET name=:n, short_name=:s"
        ), dict(id=t["id"], n=t["name"], s=t["short_name"]))

    pos_map = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    for p in tqdm(data["elements"], desc="Upserting players", unit="player"):
        session.execute(text(
            "INSERT INTO players (player_id, web_name, first_name, second_name, "
            "team_id, position, now_cost) "
            "VALUES (:id,:w,:fn,:sn,:t,:p,:c) "
            "ON CONFLICT (player_id) DO UPDATE SET "
            "web_name=:w, first_name=:fn, second_name=:sn, "
            "team_id=:t, position=:p, now_cost=:c"
        ), dict(id=p["id"], w=p["web_name"],
                fn=p.get("first_name", ""), sn=p.get("second_name", ""),
                t=p["team"], p=pos_map.get(p["element_type"]),
                c=p["now_cost"] / 10))
    session.commit()
    session.close()


def snapshot_players(data, gw):
    session = get_session()
    for p in tqdm(data["elements"], desc=f"Snapshotting GW{gw}", unit="player"):
        session.execute(text(
            "INSERT INTO player_snapshots (player_id, pulled_at, gw, minutes, "
            "season_total_points, season_goals_scored, season_assists, form, "
            "selected_by_percent, ict_index, expected_goals, expected_assists, "
            "expected_goals_conceded, now_cost, status, news) VALUES "
            "(:pid,:t,:gw,:min,:season_pts,:season_g,:season_a,:form,:sel,:ict,"
            ":xg,:xa,:xgc,:cost,:status,:news)"
        ), dict(pid=p["id"], t=datetime.utcnow(), gw=gw, min=p["minutes"],
                season_pts=p["total_points"],
                season_g=p.get("goals_scored", 0),
                season_a=p.get("assists", 0),
                form=p["form"], sel=p["selected_by_percent"], ict=p["ict_index"],
                xg=p.get("expected_goals", 0), xa=p.get("expected_assists", 0),
                xgc=p.get("expected_goals_conceded", 0), cost=p["now_cost"] / 10,
                status=p["status"], news=p.get("news", "")))
    session.commit()
    session.close()


def compute_gw_points_from_snapshots(gw: int):
    """Derives TRUE per-GW points by diffing this GW's cumulative season
    totals against the most recent prior snapshot's cumulative totals.

    v5.2 FIXES:
      1. INNER JOIN (was LEFT JOIN) — if no previous snapshot exists, skip the
         row entirely instead of writing (current - 0) = cumulative as the
         per-GW value. That's what corrupted Tzolakis's GW3 row to "270 min".
      2. ON CONFLICT ... DO UPDATE ... WHERE source != 'backfill' — never
         overwrite a genuinely per-GW row from historical_backfill. Backfill
         is authoritative; snapshot_diff is only a fallback for the freshest
         gw before the API's element-summary endpoint catches up.
      3. Only diff-write a row when points or minutes actually increased.
    """
    session = get_session()
    rows = session.execute(text("""
        WITH ranked AS (
            SELECT player_id, gw, season_total_points, season_goals_scored,
                   season_assists, minutes, ict_index, expected_goals,
                   expected_assists, now_cost,
                   ROW_NUMBER() OVER (PARTITION BY player_id
                                      ORDER BY pulled_at DESC) AS rn
            FROM player_snapshots WHERE gw <= :gw
        ),
        current AS (SELECT * FROM ranked WHERE gw = :gw AND rn = 1),
        previous AS (
            SELECT DISTINCT ON (player_id) player_id,
                   season_total_points AS prev_total,
                   season_goals_scored AS prev_goals,
                   season_assists AS prev_assists,
                   minutes AS prev_minutes,
                   ict_index AS prev_ict,
                   expected_goals AS prev_xg,
                   expected_assists AS prev_xa
            FROM ranked WHERE gw < :gw ORDER BY player_id, gw DESC
        )
        SELECT c.player_id,
               c.season_total_points - p.prev_total AS gw_points,
               c.season_goals_scored - p.prev_goals AS gw_goals,
               c.season_assists - p.prev_assists AS gw_assists,
               c.minutes - p.prev_minutes AS gw_minutes,
               c.ict_index - p.prev_ict AS gw_ict,
               c.expected_goals - p.prev_xg AS gw_xg,
               c.expected_assists - p.prev_xa AS gw_xa,
               c.now_cost
        FROM current c
        INNER JOIN previous p ON p.player_id = c.player_id
        WHERE (c.season_total_points - p.prev_total) > 0
           OR (c.minutes - p.prev_minutes) > 0
    """), dict(gw=gw)).fetchall()

    written = 0
    for r in tqdm(rows, desc=f"Per-GW points (GW{gw})", unit="player"):
        session.execute(text("""
            INSERT INTO player_gw_points
                (player_id, gw, gw_points, minutes, goals_scored, assists,
                 ict_index, expected_goals, expected_assists, now_cost, source)
            VALUES (:pid, :gw, :pts, :min, :g, :a, :ict, :xg, :xa, :cost,
                    'snapshot_diff')
            ON CONFLICT (player_id, gw) DO UPDATE SET
                gw_points = EXCLUDED.gw_points, minutes = EXCLUDED.minutes,
                goals_scored = EXCLUDED.goals_scored,
                assists = EXCLUDED.assists,
                ict_index = EXCLUDED.ict_index,
                expected_goals = EXCLUDED.expected_goals,
                expected_assists = EXCLUDED.expected_assists,
                now_cost = EXCLUDED.now_cost,
                source = 'snapshot_diff', computed_at = now()
            WHERE player_gw_points.source != 'backfill'
        """), dict(
            pid=r.player_id, gw=gw,
            pts=r.gw_points, min=r.gw_minutes,
            g=r.gw_goals, a=r.gw_assists,
            ict=r.gw_ict, xg=r.gw_xg, xa=r.gw_xa,
            cost=r.now_cost,
        ))
        written += 1
    session.commit()
    session.close()
    print(f"[fpl_source] compute_gw_points_from_snapshots(gw={gw}): "
          f"{written} rows written.")
    return written


def upsert_fixtures(fixtures_data):
    session = get_session()
    for f in tqdm(fixtures_data, desc="Upserting fixtures", unit="fixture"):
        kickoff = None
        if f.get("kickoff_time"):
            kickoff = f["kickoff_time"].replace("Z", "")
        session.execute(text("""
            INSERT INTO fixtures (fixture_id, gw, home_team_id, away_team_id,
                                   kickoff, home_goals, away_goals)
            VALUES (:id, :gw, :h, :a, :ko, :hg, :ag)
            ON CONFLICT (fixture_id) DO UPDATE SET
                gw = :gw, home_team_id = :h, away_team_id = :a, kickoff = :ko,
                home_goals = :hg, away_goals = :ag
        """), dict(id=f["id"], gw=f.get("event"), h=f["team_h"], a=f["team_a"],
                    ko=kickoff, hg=f.get("team_h_score"), ag=f.get("team_a_score")))
    session.commit()
    session.close()


def get_current_gw(data=None):
    try:
        if data is None:
            data = fetch_bootstrap()
        events = data["events"]
        for e in events:
            if e.get("is_current"):
                return e["id"]
        for e in events:
            if e.get("is_next"):
                return e["id"]
        print("[fpl_source] No is_current or is_next event.")
    except Exception as exc:
        print(f"[fpl_source] Auto-detect failed ({exc}).")
    from config import CURRENT_GW as _fallback
    print(f"[fpl_source] Falling back to config.CURRENT_GW={_fallback}.")
    return _fallback


def run_daily_ingest(gw=None):
    """gw=None (the default) auto-detects the current gameweek from the FPL
    API itself. Pass an explicit gw to override auto-detection, e.g. when
    reprocessing a past gameweek."""
    data = fetch_bootstrap()
    if gw is None:
        gw = get_current_gw(data)
        print(f"[fpl_source] Auto-detected current gameweek: GW{gw}")
    upsert_teams_and_players(data)
    upsert_fixtures(fetch_fixtures())
    snapshot_players(data, gw)

    # Compute per-GW points for the most recently COMPLETED gw. When we're
    # sitting in the middle of GW4, the last completed gw is GW3.
    completed_gw = gw - 1
    if completed_gw >= 1:
        compute_gw_points_from_snapshots(completed_gw)
    return len(data["elements"]), gw