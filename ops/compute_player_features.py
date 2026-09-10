"""Materializes player_features for a given GW. Run nightly after ingestion."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import numpy as np
from db.connection import get_session
from sqlalchemy import text


def _minutes_trend(history):
    if len(history) < 2:
        return 0.0
    recent = history[-5:]
    x = np.arange(len(recent))
    if len(set(recent)) == 1:
        return 0.0
    slope = float(np.polyfit(x, recent, 1)[0])
    return float(np.clip(slope / 90.0, -1.0, 1.0))


def compute(gw):
    session = get_session()
    try:
        players = session.execute(text(
            "SELECT player_id, team_id, position FROM players"
        )).fetchall()

        status_rows = session.execute(text("""
            SELECT DISTINCT ON (player_id) player_id, status
            FROM player_snapshots ORDER BY player_id, pulled_at DESC
        """)).fetchall()
        status_map = {r.player_id: r.status for r in status_rows}

        fdr_rows = session.execute(text("""
            SELECT team_id, AVG(fdr) AS avg_fdr FROM team_fixture_difficulty
            WHERE gw BETWEEN :gw AND :gw + 2 GROUP BY team_id
        """), dict(gw=gw)).fetchall()
        fdr_map = {r.team_id: float(r.avg_fdr or 3.0) for r in fdr_rows}

        written = 0
        for p in players:
            history_rows = session.execute(text(
                "SELECT gw, gw_points, minutes, expected_goals, expected_assists "
                "FROM player_gw_points WHERE player_id=:p AND gw < :gw ORDER BY gw"
            ), dict(p=p.player_id, gw=gw)).fetchall()

            points = [r.gw_points for r in history_rows]
            minutes = [r.minutes or 0 for r in history_rows]
            xg = sum(float(r.expected_goals or 0) for r in history_rows[-6:])
            xa = sum(float(r.expected_assists or 0) for r in history_rows[-6:])
            mins_6 = sum((r.minutes or 0) for r in history_rows[-6:])
            xgi_per_90 = (xg + xa) * 90.0 / mins_6 if mins_6 > 0 else 0.0

            def _form(n):
                recent = points[-n:]
                return float(np.mean(recent)) if recent else 0.0

            session.execute(text("""
                INSERT INTO player_features
                    (player_id, gw, form_3gw, form_6gw, form_10gw,
                     minutes_trend, xgi_per_90, injury_flag, fdr_next_3, computed_at)
                VALUES (:pid,:gw,:f3,:f6,:f10,:mt,:xgi,:inj,:fdr, now())
                ON CONFLICT (player_id, gw) DO UPDATE SET
                    form_3gw=:f3, form_6gw=:f6, form_10gw=:f10,
                    minutes_trend=:mt, xgi_per_90=:xgi, injury_flag=:inj,
                    fdr_next_3=:fdr, computed_at=now()
            """), dict(
                pid=p.player_id, gw=gw,
                f3=_form(3), f6=_form(6), f10=_form(10),
                mt=_minutes_trend(minutes),
                xgi=round(xgi_per_90, 3),
                inj=status_map.get(p.player_id, "a") != "a",
                fdr=fdr_map.get(p.team_id, 3.0),
            ))
            written += 1

        session.commit()
        print(f"[compute_player_features] Wrote {written} rows for GW{gw}.")
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, required=True)
    args = parser.parse_args()
    compute(args.gw)