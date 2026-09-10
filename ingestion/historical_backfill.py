"""Reconstructs per-GW features via element-summary. Resilient to flaky SSL."""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm
from sqlalchemy import text

from config import FPL_BASE
from db.connection import get_session


_http_session = None


def get_http_session() -> requests.Session:
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


def fetch_player_history(player_id):
    s = get_http_session()
    r = s.get(f"{FPL_BASE}/element-summary/{player_id}/", timeout=(10, 30))
    r.raise_for_status()
    return r.json()["history"]


UPSERT_SQL = text("""
    INSERT INTO player_gw_points
        (player_id, gw, gw_points, minutes, goals_scored, assists, ict_index,
         expected_goals, expected_assists, now_cost, source)
    VALUES (:pid, :gw, :pts, :min, :g, :a, :ict, :xg, :xa, :cost, 'backfill')
    ON CONFLICT (player_id, gw) DO UPDATE SET
        gw_points = EXCLUDED.gw_points, minutes = EXCLUDED.minutes,
        goals_scored = EXCLUDED.goals_scored, assists = EXCLUDED.assists,
        ict_index = EXCLUDED.ict_index, expected_goals = EXCLUDED.expected_goals,
        expected_assists = EXCLUDED.expected_assists,
        now_cost = EXCLUDED.now_cost, source = 'backfill', computed_at = now()
""")


def backfill_all(player_ids, request_pause=0.15):
    session = get_session()
    inserted = 0
    failed = []
    pbar = tqdm(player_ids, desc="Backfilling player history", unit="player")
    for pid in pbar:
        try:
            history = fetch_player_history(pid)
        except Exception as e:
            failed.append((pid, repr(e)))
            pbar.set_postfix(rows_inserted=inserted, failed=len(failed))
            time.sleep(1.0)
            continue
        try:
            for gw_row in history:
                session.execute(UPSERT_SQL, dict(
                    pid=pid, gw=gw_row["round"], pts=gw_row["total_points"],
                    min=gw_row["minutes"], g=gw_row.get("goals_scored", 0),
                    a=gw_row.get("assists", 0), ict=gw_row.get("ict_index"),
                    xg=gw_row.get("expected_goals", 0),
                    xa=gw_row.get("expected_assists", 0),
                    cost=gw_row["value"] / 10))
                inserted += 1
            session.commit()
        except Exception as e:
            session.rollback()
            failed.append((pid, f"db error: {e!r}"))
            pbar.set_postfix(rows_inserted=inserted, failed=len(failed))
            time.sleep(0.5)
            continue
        pbar.set_postfix(rows_inserted=inserted, failed=len(failed))
        time.sleep(request_pause)
    session.commit()
    session.close()

    if failed:
        print(f"\n{len(failed)} player(s) failed:")
        for pid, err in failed[:25]:
            print(f"  player_id={pid}: {err}")
    return inserted


if __name__ == "__main__":
    session = get_session()
    player_ids = [r.player_id for r in session.execute(
        text("SELECT player_id FROM players")).fetchall()]
    session.close()
    if not player_ids:
        print("No players yet -- run ops.retrain_job first.")
    else:
        n = backfill_all(player_ids)
        print(f"Backfilled {n} rows across {len(player_ids)} players.")