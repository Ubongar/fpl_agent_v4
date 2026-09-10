"""Imports your real FPL squad for the target GW by pulling the PREVIOUS GW's
picks (the current GW's picks aren't available until after its deadline).

v5.1: --replace (default ON) deletes any existing user_squad rows for the
target GW before inserting the fresh 15, so re-running the import after a
mistake can't leave you with 25 rows.
"""
import requests
import argparse
from db.connection import get_session
from sqlalchemy import text


def import_team(team_id: int, target_gw: int, replace: bool = True):
    prev_gw = target_gw - 1
    url = (f"https://fantasy.premierleague.com/api/entry/{team_id}"
           f"/event/{prev_gw}/picks/")

    print(f"Fetching your team from FPL API: {url}")
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        print(f"Failed to fetch team (status {r.status_code}). "
              f"Check your Team ID and that GW{prev_gw} has finished.")
        return

    data = r.json()
    picks = data.get("picks", [])
    entry_history = data.get("entry_history", {})
    bank = float(entry_history.get("bank", 0)) / 10.0
    free_transfers = int(entry_history.get("event_transfers", 1)) or 1

    if not picks:
        print(f"No picks returned for GW{prev_gw}. The GW may not be complete.")
        return

    if len(picks) != 15:
        print(f"WARNING: API returned {len(picks)} picks (expected 15). "
              f"Continuing anyway, but check the data.")

    session = get_session()
    try:
        if replace:
            deleted = session.execute(text(
                "DELETE FROM user_squad WHERE gw = :gw"
            ), dict(gw=target_gw)).rowcount
            if deleted:
                print(f"Cleared {deleted} existing row(s) for GW{target_gw}.")

        inserted = 0
        for pick in picks:
            player_id = pick["element"]
            is_starting = pick["position"] <= 11
            is_captain = bool(pick.get("is_captain", False))

            cost_row = session.execute(
                text("SELECT now_cost FROM players WHERE player_id = :p"),
                dict(p=player_id)
            ).fetchone()
            bought_price = float(cost_row.now_cost) if cost_row else 0.0

            session.execute(text("""
                INSERT INTO user_squad
                    (player_id, gw, bought_price, is_starting, is_captain)
                VALUES (:pid, :gw, :price, :start, :cap)
                ON CONFLICT (player_id, gw) DO UPDATE SET
                    bought_price = EXCLUDED.bought_price,
                    is_starting = EXCLUDED.is_starting,
                    is_captain = EXCLUDED.is_captain
            """), dict(pid=player_id, gw=target_gw, price=bought_price,
                        start=is_starting, cap=is_captain))
            inserted += 1

        session.execute(text("""
            INSERT INTO team_meta (gw, bank, free_transfers)
            VALUES (:gw, :bank, :ft)
            ON CONFLICT (gw) DO UPDATE SET
                bank = EXCLUDED.bank, free_transfers = EXCLUDED.free_transfers
        """), dict(gw=target_gw, bank=bank, ft=free_transfers))

        session.commit()
        print(f"Imported {inserted} players into GW{target_gw} squad.")
        print(f"Bank: £{bank:.1f}m · Free transfers: {free_transfers}")
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--team_id", type=int, required=True,
                         help="Your official FPL Team ID (the number in the "
                              "URL when you open your team on the FPL site).")
    parser.add_argument("--gw", type=int, required=True,
                         help="Target gameweek (e.g. 4). The importer pulls "
                              "your GW-1 picks as the baseline.")
    parser.add_argument("--no-replace", action="store_true",
                         help="Do NOT clear existing rows for this GW first.")
    args = parser.parse_args()
    import_team(args.team_id, args.gw, replace=not args.no_replace)