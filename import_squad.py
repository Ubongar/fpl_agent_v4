import requests
import argparse
from db.connection import get_session
from sqlalchemy import text

def import_team(team_id: int, target_gw: int):
    # We fetch your finalized GW3 picks to act as the baseline for the GW4 optimizer
    prev_gw = target_gw - 1
    url = f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{prev_gw}/picks/"
    
    print(f"Fetching your team from FPL API: {url}")
    r = requests.get(url, timeout=15)
    
    if r.status_code != 200:
        print("Failed to fetch team. Make sure your Team ID is correct.")
        return

    data = r.json()
    picks = data.get("picks", [])
    
    session = get_session()
    inserted = 0
    
    for pick in picks:
        player_id = pick["element"]
        is_starting = pick["position"] <= 11
        is_captain = pick["is_captain"]
        
        # Use current cost as a proxy for bought_price since the public API hides financial data
        cost_row = session.execute(
            text("SELECT now_cost FROM players WHERE player_id = :p"), 
            dict(p=player_id)
        ).fetchone()
        bought_price = float(cost_row.now_cost) if cost_row else 0.0
        
        # Insert into user_squad
        session.execute(text("""
            INSERT INTO user_squad (player_id, gw, bought_price, is_starting, is_captain)
            VALUES (:pid, :gw, :price, :start, :cap)
            ON CONFLICT (player_id, gw) DO UPDATE SET
                is_starting = EXCLUDED.is_starting,
                is_captain = EXCLUDED.is_captain
        """), dict(pid=player_id, gw=target_gw, price=bought_price, start=is_starting, cap=is_captain))
        inserted += 1
        
    # Insert default team meta (1 free transfer, £0.0m in the bank)
    # You can update this row manually in your database if you have money in the bank
    session.execute(text("""
        INSERT INTO team_meta (gw, bank, free_transfers)
        VALUES (:gw, 0.0, 1)
        ON CONFLICT (gw) DO NOTHING
    """), dict(gw=target_gw))
        
    session.commit()
    session.close()
    
    print(f"Successfully imported {inserted} players into your Gameweek {target_gw} squad!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--team_id", type=int, required=True, help="Your official FPL Team ID")
    parser.add_argument("--gw", type=int, required=True, help="The target Gameweek (e.g., 4)")
    args = parser.parse_args()
    import_team(args.team_id, args.gw)