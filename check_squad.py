import argparse
from db.connection import get_session
from sqlalchemy import text

def check_my_team(gw: int):
    session = get_session()
    
    # Count the number of players in the user_squad table for this GW
    row = session.execute(
        text("SELECT COUNT(*) AS player_count FROM user_squad WHERE gw = :gw"), 
        dict(gw=gw)
    ).fetchone()
    
    count = row.player_count
    print(f"You have {count} players saved in your squad for Gameweek {gw}.")
    
    if count == 15:
        print("Ready to run the optimizers!")
    elif count == 0:
        print("Your squad is empty. We need to fetch it from the FPL API.")
    else:
        print(f"Your squad has {count} players. You need exactly 15.")
        
    session.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, required=True, help="The Gameweek to check (e.g. 4)")
    args = parser.parse_args()
    check_my_team(args.gw)