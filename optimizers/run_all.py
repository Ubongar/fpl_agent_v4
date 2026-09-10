"""Master execution pipeline for FPL Agent v4.
Fetches the user's squad and bank, runs the transfer and captaincy optimizers,
and logs the final recommendations for evaluation.

Canonical squad/candidate dict shape (all numerics cast Decimal -> float):
    {player_id, name, first_name, second_name, pos, price,
     xp_mean, p10, p50, p90, start_prob}

Display names are built via display_name() so players who share a web_name
(e.g. Callum Wilson vs Harry Wilson) are always distinguishable in output
and logs. Every log payload also includes the player_id(s).
"""

import sys
import os

# Make project root importable when running this file directly
# (e.g. `python optimizers/run_all.py`), not just as a module.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from db.connection import get_session
from sqlalchemy import text

from optimizers.transfer import best_single_transfer
from optimizers.captaincy import rank_captains
from ops.tracking import log_recommendation


REQUIRED_SQUAD_KEYS = {
    "player_id", "name", "first_name", "second_name", "pos", "price",
    "xp_mean", "p10", "p50", "p90", "start_prob",
}


def _to_float(d: dict, keys) -> dict:
    """Cast Postgres NUMERIC (Decimal) fields to plain float in-place.
    SQLAlchemy returns NUMERIC as decimal.Decimal, which refuses to mix with
    float in arithmetic (`Decimal + float -> TypeError`)."""
    for k in keys:
        if k in d and d[k] is not None:
            d[k] = float(d[k])
    return d


def display_name(p: dict) -> str:
    """Unique display name, e.g. 'Callum Wilson' vs 'Harry Wilson'. Falls
    back to web_name if first/second are missing."""
    first = (p.get("first_name") or "").strip()
    second = (p.get("second_name") or "").strip()
    full = f"{first} {second}".strip()
    return full if full else (p.get("name") or "Unknown")


def get_squad_and_candidates(session, gw):
    """Formats database rows into the exact dictionary shapes required by
    the optimizers."""

    # 1. Current squad joined with their GW predictions
    squad_rows = session.execute(text("""
        SELECT p.player_id, p.web_name AS name,
               p.first_name, p.second_name,
               p.position AS pos, p.now_cost AS price,
               pr.xp_mean, pr.xp_p10 AS p10, pr.xp_p50 AS p50,
               pr.xp_p90 AS p90, pr.start_prob
        FROM user_squad us
        JOIN players p ON p.player_id = us.player_id
        JOIN predictions pr ON pr.player_id = p.player_id
        WHERE us.gw = :gw AND pr.gw = :gw
    """), dict(gw=gw)).fetchall()

    squad = []
    for r in squad_rows:
        d = _to_float(
            dict(r._mapping),
            ("price", "xp_mean", "p10", "p50", "p90", "start_prob"),
        )
        missing = REQUIRED_SQUAD_KEYS - d.keys()
        if missing:
            raise KeyError(
                f"squad row player_id={d.get('player_id')} missing keys: "
                f"{sorted(missing)} (has: {sorted(d.keys())})"
            )
        squad.append(d)

    # 2. All viable candidates in the game for transfers
    candidate_rows = session.execute(text("""
        SELECT p.player_id, p.web_name AS name,
               p.first_name, p.second_name,
               p.position AS pos, p.now_cost AS price,
               pr.xp_mean, pr.start_prob
        FROM predictions pr
        JOIN players p ON p.player_id = pr.player_id
        WHERE pr.gw = :gw
    """), dict(gw=gw)).fetchall()

    candidates = [
        _to_float(dict(r._mapping), ("price", "xp_mean", "start_prob"))
        for r in candidate_rows
    ]

    # 3. Team meta (bank / free transfers)
    meta = session.execute(
        text("SELECT bank, free_transfers FROM team_meta WHERE gw = :gw"),
        dict(gw=gw),
    ).fetchone()
    bank = float(meta.bank) if meta else 0.0

    return squad, candidates, bank


def run_pipeline(gw: int):
    session = get_session()
    print(f"--- Running FPL Agent v4 Optimizers for GW{gw} ---")

    try:
        squad, candidates, bank = get_squad_and_candidates(session, gw)

        if not squad:
            print(
                "Error: No players found in user_squad for this GW. "
                "Make sure your team is populated!"
            )
            return

        # --- 1. TRANSFER OPTIMIZATION ---
        transfer_plan = best_single_transfer(squad, candidates, bank)
        if transfer_plan:
            out_name = display_name(transfer_plan["out"])
            in_name = display_name(transfer_plan["in"])

            print("\n[TRANSFER RECOMMENDED]")
            print(f"OUT: {out_name} (xP: {transfer_plan['out']['xp_mean']})")
            print(f"IN:  {in_name} (xP: {transfer_plan['in']['xp_mean']})")
            print(f"Net Gain: +{transfer_plan['gain']} xP")

            # Log with player_ids so future-you knows WHICH Wilson.
            log_recommendation(gw, "transfer", {
                "out_id": transfer_plan["out"]["player_id"],
                "out_name": out_name,
                "in_id": transfer_plan["in"]["player_id"],
                "in_name": in_name,
                "gain": transfer_plan["gain"],
            })
        else:
            print(
                "\n[TRANSFER] No transfers yield a positive expected points "
                "gain. Roll the transfer."
            )

        # --- 2. CAPTAINCY OPTIMIZATION ---
        ranked_captains = rank_captains(squad)
        if len(ranked_captains) < 2:
            print("\n[CAPTAINCY] Need at least 2 squad players to rank captains.")
            return

        top_c = ranked_captains[0]
        top_vc = ranked_captains[1]
        c_name = display_name(top_c)
        vc_name = display_name(top_vc)

        print("\n[CAPTAINCY RECOMMENDED]")
        print(
            f"Captain: {c_name} "
            f"(Score: {top_c['captaincy_score']}, Ceiling: {top_c['p90']})"
        )
        print(
            f"Vice-Captain: {vc_name} "
            f"(Score: {top_vc['captaincy_score']})"
        )

        log_recommendation(gw, "captaincy", {
            "captain_id": top_c["player_id"],
            "captain_name": c_name,
            "vice_id": top_vc["player_id"],
            "vice_name": vc_name,
        })

        print("\nRecommendations logged successfully.")
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, required=True)
    args = parser.parse_args()
    run_pipeline(args.gw)   