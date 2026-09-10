"""Reconstructs per-GW features for past gameweeks using FPL's element-summary
"history" endpoint. Unlike bootstrap-static, each row in this endpoint's
history list IS genuinely per-fixture/per-GW already -- no diffing needed here.

BUG FIX (v4): the original ON CONFLICT DO NOTHING referenced no real unique
constraint, so re-running backfill silently duplicated every row. Fixed by
writing to player_gw_points, which now has a real UNIQUE(player_id, gw)
constraint (see db/schema.sql), and using DO UPDATE so reruns correct
existing rows instead of duplicating or silently no-op'ing on conflict.

BUG FIX (v5): SSL handshake / read timeouts were killing the entire run on
a single flaky player. Fixed by:
  - Reusing a single requests.Session (TCP+TLS connection reuse).
  - Mounting an HTTPAdapter with urllib3.Retry + backoff on connect/read/5xx.
  - Per-player try/except so one bad player doesn't abort the whole backfill.
  - Per-player commit so a crash only loses the current player's rows.
  - Polite sleep between requests to avoid tripping FPL's CDN rate limiter.
  - Explicit (connect, read) timeouts and a real User-Agent header.
"""
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


# --------------------------------------------------------------------------- #
# HTTP session (module-level singleton, reused across all player fetches)
# --------------------------------------------------------------------------- #
_http_session = None


def get_http_session() -> requests.Session:
    """Return a shared requests.Session configured with retries + pooling.
    Reusing one session avoids a fresh TLS handshake per request, which was
    the root cause of the '_ssl.c: handshake operation timed out' errors."""
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


def fetch_player_history(player_id: int):
    """Fetch a player's per-GW history rows from the FPL element-summary endpoint."""
    s = get_http_session()
    r = s.get(
        f"{FPL_BASE}/element-summary/{player_id}/",
        timeout=(10, 30),
    )
    r.raise_for_status()
    return r.json()["history"]


# --------------------------------------------------------------------------- #
# Backfill
# --------------------------------------------------------------------------- #
UPSERT_SQL = text("""
    INSERT INTO player_gw_points
        (player_id, gw, gw_points, minutes, goals_scored, assists, ict_index,
         expected_goals, expected_assists, now_cost, source)
    VALUES (:pid, :gw, :pts, :min, :g, :a, :ict, :xg, :xa, :cost, 'backfill')
    ON CONFLICT (player_id, gw) DO UPDATE SET
        gw_points = EXCLUDED.gw_points,
        minutes = EXCLUDED.minutes,
        goals_scored = EXCLUDED.goals_scored,
        assists = EXCLUDED.assists,
        ict_index = EXCLUDED.ict_index,
        expected_goals = EXCLUDED.expected_goals,
        expected_assists = EXCLUDED.expected_assists,
        now_cost = EXCLUDED.now_cost,
        source = 'backfill',
        computed_at = now()
""")


def backfill_all(player_ids, request_pause: float = 0.15):
    """Backfill per-GW rows for every player_id. Returns rows written.
    Per-player errors are caught and reported at the end; the run continues
    so a single flaky player can't kill the whole backfill."""
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
                    pid=pid,
                    gw=gw_row["round"],
                    pts=gw_row["total_points"],
                    min=gw_row["minutes"],
                    g=gw_row.get("goals_scored", 0),
                    a=gw_row.get("assists", 0),
                    ict=gw_row.get("ict_index"),
                    xg=gw_row.get("expected_goals", 0),
                    xa=gw_row.get("expected_assists", 0),
                    cost=gw_row["value"] / 10,
                ))
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
        if len(failed) > 25:
            print(f"  ... and {len(failed) - 25} more")

    return inserted


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    session = get_session()
    player_ids = [
        r.player_id
        for r in session.execute(text("SELECT player_id FROM players")).fetchall()
    ]
    session.close()

    if not player_ids:
        print(
            "No players in the `players` table yet -- run "
            "`python ops/retrain_job.py` first to populate teams and players, "
            "then re-run this backfill."
        )
    else:
        n = backfill_all(player_ids)
        print(f"Backfilled {n} player-gameweek rows across {len(player_ids)} players.")