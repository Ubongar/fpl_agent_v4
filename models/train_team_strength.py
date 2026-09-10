"""Computes real attack/defence ratings per team from actual fixture results
(fixtures.home_goals/away_goals), replacing any placeholder/assumed inputs to
team_strength.update_team_strength(). Home and away ratings are computed
separately from each team's home-only and away-only result history, matching
the team_strength table's attack_home/attack_away/defence_home/defence_away
columns.

Usage:
    python -m models.train_team_strength [--gw N]

Writes one row per team into team_strength for the given gw (defaults to the
latest gw with any finished fixture).
"""
import argparse
from db.connection import get_session
from sqlalchemy import text
from models.team_strength import update_team_strength


def build_team_histories(fixture_rows):
    """Pure function: fixture_rows -> {team_id: {"home": (gf_list, ga_list),
    "away": (gf_list, ga_list)}}, in ascending gw order. No DB, no I/O --
    testable directly with synthetic rows."""
    fixture_rows = sorted(fixture_rows, key=lambda r: r["gw"])
    hist = {}
    for r in fixture_rows:
        if r["home_goals"] is None or r["away_goals"] is None:
            continue  # unfinished fixture -- never treat NULL as 0-0
        h, a = r["home_team_id"], r["away_team_id"]
        hg, ag = r["home_goals"], r["away_goals"]
        hist.setdefault(h, {"home": ([], []), "away": ([], [])})
        hist.setdefault(a, {"home": ([], []), "away": ([], [])})
        hist[h]["home"][0].append(hg)
        hist[h]["home"][1].append(ag)
        hist[a]["away"][0].append(ag)
        hist[a]["away"][1].append(hg)
    return hist


def ratings_from_histories(hist: dict) -> dict:
    """{team_id: {"home": {...}} -> {team_id: {attack_home, defence_home,
    attack_away, defence_away}}. Also pure -- no DB."""
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
    q = "SELECT gw, home_team_id, away_team_id, home_goals, away_goals FROM fixtures WHERE home_goals IS NOT NULL"
    params = {}
    if up_to_gw is not None:
        q += " AND gw <= :gw"
        params["gw"] = up_to_gw
    rows = session.execute(text(q), params).fetchall()
    return [dict(gw=r.gw, home_team_id=r.home_team_id, away_team_id=r.away_team_id,
                 home_goals=r.home_goals, away_goals=r.away_goals) for r in rows]


def train_and_save(gw: int = None):
    session = get_session()
    fixture_rows = fetch_finished_fixtures(session, up_to_gw=gw)
    if len(fixture_rows) < 10:
        print(f"Only {len(fixture_rows)} finished fixtures -- too little history "
              f"for reliable ratings yet. Skipping; downstream code should keep "
              f"using team_strength's neutral 1.0/1.0 default.")
        session.close()
        return None

    as_of_gw = gw if gw is not None else max(r["gw"] for r in fixture_rows)
    hist = build_team_histories(fixture_rows)
    ratings = ratings_from_histories(hist)

    for team_id, r in ratings.items():
        session.execute(text(
            "INSERT INTO team_strength (team_id, gw, attack_home, attack_away, "
            "defence_home, defence_away) VALUES (:t,:gw,:ah,:aa,:dh,:da) "
            "ON CONFLICT (team_id, gw) DO UPDATE SET attack_home=:ah, "
            "attack_away=:aa, defence_home=:dh, defence_away=:da"
        ), dict(t=team_id, gw=as_of_gw, ah=r["attack_home"], aa=r["attack_away"],
                dh=r["defence_home"], da=r["defence_away"]))
    session.commit()
    session.close()
    print(f"Wrote ratings for {len(ratings)} teams as of gw{as_of_gw}, from {len(fixture_rows)} finished fixtures.")
    return ratings


def get_latest_ratings(session, team_id, as_of_gw):
    """Read helper for the expected_points pipeline: latest computed rating
    for a team at or before as_of_gw, or the neutral default if none exists
    yet -- this is the ONLY place a 1.0/1.0 default should come from at
    prediction time, so it's explicit rather than silently baked in."""
    row = session.execute(text(
        "SELECT attack_home, attack_away, defence_home, defence_away FROM team_strength "
        "WHERE team_id=:t AND gw<=:gw ORDER BY gw DESC LIMIT 1"
    ), dict(t=team_id, gw=as_of_gw)).fetchone()
    if row is None:
        return {"attack_home": 1.0, "attack_away": 1.0, "defence_home": 1.0, "defence_away": 1.0, "source": "no_history_default"}
    # Cast the PostgreSQL Decimal types to Python floats here
    return {
        "attack_home": float(row.attack_home), 
        "attack_away": float(row.attack_away),
        "defence_home": float(row.defence_home), 
        "defence_away": float(row.defence_away), 
        "source": "trained"
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, default=None)
    args = parser.parse_args()
    train_and_save(gw=args.gw)