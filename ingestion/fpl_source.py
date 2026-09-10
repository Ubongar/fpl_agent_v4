"""Official FPL API ingestion -> immutable snapshots + derived per-GW points.

BUG FIX (v4): bootstrap-static's "total_points" is a SEASON-CUMULATIVE total,
not a per-gameweek score. v3 stored it directly as if it were per-GW, which
would have silently corrupted any rolling_form calculation built on top of it.
Fixed by: (1) storing it under the honestly-named `season_total_points` column
in the immutable player_snapshots log, and (2) deriving true per-GW points via
compute_gw_points_from_snapshots(), which diffs consecutive cumulative totals
and writes the result to player_gw_points -- the ONLY table models should read
per-GW figures from.

BUG FIX (v5): switched bootstrap + fixtures fetches to a shared requests.Session
with urllib3.Retry backoff. The per-call `requests.get(..., timeout=15)` was
hitting the same intermittent `_ssl.c: handshake operation timed out` errors
that were killing historical_backfill.py on a fresh TLS handshake per request.
Also stores `first_name` and `second_name` on players so downstream output
can disambiguate e.g. Callum Wilson vs Harry Wilson.
"""
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
from tqdm import tqdm
from config import FPL_BASE
from db.connection import get_session
from sqlalchemy import text


# --------------------------------------------------------------------------- #
# HTTP session (module-level singleton, reused across all FPL API calls)
# --------------------------------------------------------------------------- #
_http_session = None


def get_http_session() -> requests.Session:
    """Shared requests.Session with retries + pooling. Avoids a fresh TLS
    handshake per call, which was the root cause of intermittent
    'handshake operation timed out' errors on the FPL API."""
    global _http_session
    if _http_session is not None:
        return _http_session

    s = requests.Session()
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.5,                          # 0s, 1.5s, 3s, 6s, 12s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({
        "User-Agent": "fpl-agent/1.0 (personal research)",
        "Accept": "application/json",
    })
    _http_session = s
    return s


def _get_json(path: str):
    s = get_http_session()
    r = s.get(f"{FPL_BASE}{path}", timeout=(10, 30))
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------- #
# Fetchers
# --------------------------------------------------------------------------- #
def fetch_bootstrap():
    return _get_json("/bootstrap-static/")


def fetch_fixtures():
    return _get_json("/fixtures/")


# --------------------------------------------------------------------------- #
# Upserts
# --------------------------------------------------------------------------- #
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
        ), dict(
            id=p["id"],
            w=p["web_name"],
            fn=p.get("first_name", ""),
            sn=p.get("second_name", ""),
            t=p["team"],
            p=pos_map.get(p["element_type"]),
            c=p["now_cost"] / 10,
        ))
    session.commit()
    session.close()


def snapshot_players(data, gw):
    """Insert one immutable row per player for this pull. `season_total_points`,
    `season_goals_scored`, and `season_assists` are all explicitly cumulative --
    do NOT treat any of them as this gameweek's figure."""
    session = get_session()
    for p in tqdm(data["elements"], desc=f"Snapshotting GW{gw}", unit="player"):
        session.execute(text(
            "INSERT INTO player_snapshots (player_id, pulled_at, gw, minutes, "
            "season_total_points, season_goals_scored, season_assists, form, "
            "selected_by_percent, ict_index, expected_goals, expected_assists, "
            "expected_goals_conceded, now_cost, status, news) VALUES "
            "(:pid,:t,:gw,:min,:season_pts,:season_g,:season_a,:form,:sel,:ict,"
            ":xg,:xa,:xgc,:cost,:status,:news)"
        ), dict(
            pid=p["id"], t=datetime.utcnow(), gw=gw, min=p["minutes"],
            season_pts=p["total_points"],
            season_g=p.get("goals_scored", 0),
            season_a=p.get("assists", 0),
            form=p["form"], sel=p["selected_by_percent"], ict=p["ict_index"],
            xg=p.get("expected_goals", 0), xa=p.get("expected_assists", 0),
            xgc=p.get("expected_goals_conceded", 0), cost=p["now_cost"] / 10,
            status=p["status"], news=p.get("news", ""),
        ))
    session.commit()
    session.close()


def compute_gw_points_from_snapshots(gw: int):
    """Derives TRUE per-GW points by diffing this GW's cumulative season total
    against the most recent prior snapshot's cumulative total, per player.
    Idempotent thanks to the real UNIQUE(player_id, gw) constraint on
    player_gw_points -- re-running for the same gw corrects the row rather
    than duplicating it."""
    session = get_session()
    rows = session.execute(text("""
        WITH ranked AS (
            SELECT player_id, gw, season_total_points, season_goals_scored, season_assists,
                   minutes, ict_index, expected_goals, expected_assists, now_cost,
                   ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY pulled_at DESC) AS rn
            FROM player_snapshots WHERE gw <= :gw
        ),
        current AS (SELECT * FROM ranked WHERE gw = :gw AND rn = 1),
        previous AS (
            SELECT DISTINCT ON (player_id) player_id, season_total_points AS prev_total,
                   season_goals_scored AS prev_goals, season_assists AS prev_assists
            FROM ranked WHERE gw < :gw ORDER BY player_id, gw DESC
        )
        SELECT c.player_id, c.season_total_points - COALESCE(p.prev_total, 0) AS gw_points,
               c.season_goals_scored - COALESCE(p.prev_goals, 0) AS gw_goals,
               c.season_assists - COALESCE(p.prev_assists, 0) AS gw_assists,
               c.minutes, c.ict_index, c.expected_goals, c.expected_assists, c.now_cost
        FROM current c LEFT JOIN previous p ON p.player_id = c.player_id
    """), dict(gw=gw)).fetchall()

    for r in tqdm(rows, desc=f"Computing per-GW points (GW{gw})", unit="player"):
        session.execute(text("""
            INSERT INTO player_gw_points
                (player_id, gw, gw_points, minutes, goals_scored, assists, ict_index,
                 expected_goals, expected_assists, now_cost, source)
            VALUES (:pid, :gw, :pts, :min, :g, :a, :ict, :xg, :xa, :cost, 'snapshot_diff')
            ON CONFLICT (player_id, gw) DO UPDATE SET
                gw_points = EXCLUDED.gw_points, minutes = EXCLUDED.minutes,
                goals_scored = EXCLUDED.goals_scored, assists = EXCLUDED.assists,
                ict_index = EXCLUDED.ict_index, expected_goals = EXCLUDED.expected_goals,
                expected_assists = EXCLUDED.expected_assists, now_cost = EXCLUDED.now_cost,
                source = 'snapshot_diff', computed_at = now()
        """), dict(
            pid=r.player_id, gw=gw, pts=r.gw_points, min=r.minutes,
            g=r.gw_goals, a=r.gw_assists, ict=r.ict_index,
            xg=r.expected_goals, xa=r.expected_assists, cost=r.now_cost,
        ))
    session.commit()
    session.close()
    return len(rows)


def upsert_fixtures(fixtures_data):
    """Writes real fixture rows (gw, teams, kickoff, and final score once played)
    into the `fixtures` table. Nothing previously called fetch_fixtures() or
    wrote its result anywhere -- train_team_strength.py and run_predictions.py
    both read from this table, so without this it silently looks like there
    are simply no fixtures at all."""
    session = get_session()
    for f in tqdm(fixtures_data, desc="Upserting fixtures", unit="fixture"):
        kickoff = None
        if f.get("kickoff_time"):
            kickoff = f["kickoff_time"].replace("Z", "")
        session.execute(text("""
            INSERT INTO fixtures (fixture_id, gw, home_team_id, away_team_id, kickoff, home_goals, away_goals)
            VALUES (:id, :gw, :h, :a, :ko, :hg, :ag)
            ON CONFLICT (fixture_id) DO UPDATE SET
                gw = :gw, home_team_id = :h, away_team_id = :a, kickoff = :ko,
                home_goals = :hg, away_goals = :ag
        """), dict(
            id=f["id"], gw=f.get("event"), h=f["team_h"], a=f["team_a"],
            ko=kickoff, hg=f.get("team_h_score"), ag=f.get("team_a_score"),
        ))
    session.commit()
    session.close()


def get_current_gw(data=None):
    """Determines which gameweek to ingest/snapshot straight from the FPL
    API's own bootstrap-static `events` list. Picks the event flagged
    `is_current`, falls back to `is_next`, then to config.CURRENT_GW."""
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
        print("[fpl_source] No gameweek flagged is_current or is_next in the API response.")
    except Exception as exc:
        print(f"[fpl_source] Could not auto-detect current gameweek from the FPL API ({exc}).")
    from config import CURRENT_GW as _fallback_gw
    print(f"[fpl_source] Falling back to config.CURRENT_GW={_fallback_gw}.")
    return _fallback_gw


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
    if gw > 1:
        compute_gw_points_from_snapshots(gw)
    return len(data["elements"]), gw