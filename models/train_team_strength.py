"""Computes attack/defence ratings per team from real fixture results.
Usage: python -m models.train_team_strength [--gw N]"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from db.connection import get_session
from sqlalchemy import text
from models.team_strength import update_team_strength


def build_team_histories(fixture_rows):
    fixture_rows = sorted(fixture_rows, key=lambda r: r["gw"])
    hist = {}
    for r in fixture_rows:
        if r["home_goals"] is None or r["away_goals"] is None:
            continue
        h, a = r["home_team_id"], r["away_team_id"]
        hg, ag = r["home_goals"], r["away_goals"]
        hist.setdefault(h, {"home": ([], []), "away": ([], [])})
        hist.setdefault(a, {"home": ([], []), "away": ([], [])})
        hist[h]["home"][0].append(hg); hist[h]["home"][1].append(ag)
        hist[a]["away"][0].append(ag); hist[a]["away"][1].append(hg)
    return hist


def ratings_from_histories(hist):
    out = {}
    for team_id, splits in hist.items():
        home_gf, home_ga = splits["home"]
        away_gf, away_ga = splits["away"]
        home_r = update_team_strength(home_gf, home_ga)
        away_r = update_team_strength(away_gf, away_ga)
        out[team_id] = {
            "attack_home": home_r["attack"], "defence_home": home_r["defence"],
            "attack_away": away_r["attack"], "defence_away": away_r["defence"],
        }
    return out


def fetch_finished_fixtures(session, up_to_gw=None):
    q = ("SELECT gw, home_team_id, away_team_id, home_goals, away_goals "
         "FROM fixtures WHERE home_goals IS NOT NULL")
    params = {}
    if up_to_gw is not None:
        q += " AND gw <= :gw"
        params["gw"] = up_to_gw
    rows = session.execute(text(q), params).fetchall()
    return [dict(gw=r.gw, home_team_id=r.home_team_id, away_team_id=r.away_team_id,
                 home_goals=r.home_goals, away_goals=r.away_goals) for r in rows]


def train_and_save(gw: int = None):
    session = get_session()
    all_fixtures = fetch_finished_fixtures(session)   # no up_to_gw filter

    if len(all_fixtures) < 10:
        print(f"[train_team_strength] Only {len(all_fixtures)} finished fixtures. "
              f"Need >=10. Skipping.")
        session.close()
        return None

    max_gw = gw if gw is not None else max(r["gw"] for r in all_fixtures)
    total_rows = 0

    for as_of in range(1, max_gw + 1):
        gw_fixtures = [r for r in all_fixtures if r["gw"] <= as_of]
        if not gw_fixtures:
            continue
        hist = build_team_histories(gw_fixtures)
        ratings = ratings_from_histories(hist)
        for team_id, r in ratings.items():
            session.execute(text(
                "INSERT INTO team_strength (team_id, gw, attack_home, attack_away, "
                "defence_home, defence_away) VALUES (:t,:gw,:ah,:aa,:dh,:da) "
                "ON CONFLICT (team_id, gw) DO UPDATE SET attack_home=:ah, "
                "attack_away=:aa, defence_home=:dh, defence_away=:da"
            ), dict(t=team_id, gw=as_of, ah=r["attack_home"], aa=r["attack_away"],
                    dh=r["defence_home"], da=r["defence_away"]))
            total_rows += 1
        session.commit()
        print(f"[train_team_strength] gw{as_of}: wrote {len(ratings)} team ratings "
              f"from {len(gw_fixtures)} fixtures.")

    session.close()
    print(f"[train_team_strength] Done. {total_rows} total rows.")
    return None


def get_latest_ratings(session, team_id, as_of_gw):
    row = session.execute(text(
        "SELECT attack_home, attack_away, defence_home, defence_away "
        "FROM team_strength WHERE team_id=:t AND gw<=:gw "
        "ORDER BY gw DESC LIMIT 1"
    ), dict(t=team_id, gw=as_of_gw)).fetchone()
    if row is None:
        return {"attack_home": 1.0, "attack_away": 1.0,
                "defence_home": 1.0, "defence_away": 1.0,
                "source": "no_history_default"}
    return {
        "attack_home": float(row.attack_home),
        "attack_away": float(row.attack_away),
        "defence_home": float(row.defence_home),
        "defence_away": float(row.defence_away),
        "source": "trained",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, default=None)
    args = parser.parse_args()
    train_and_save(gw=args.gw)