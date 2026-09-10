"""Master execution pipeline for FPL Agent v4.
Fetches the user's squad and bank, runs the transfer and captaincy optimizers,
and logs the final recommendations for evaluation."""

import argparse
from db.connection import get_session
from sqlalchemy import text

# Adjust these imports based on your exact folder structure
from optimizers.transfer import best_single_transfer
from optimizers.captaincy import rank_captains
from ops.tracking import log_recommendation

def get_squad_and_candidates(session, gw):
    """Formats database rows into the exact dictionary shapes required by the optimizers."""
    # 1. Get current squad joined with their new GW predictions
    squad_rows = session.execute(text("""
        SELECT p.player_id, p.web_name AS name, p.position AS pos, p.now_cost AS price, 
               pr.xp_mean AS xp, pr.xp_p10 AS p10, pr.xp_p50 AS p50, pr.xp_p90 AS p90, pr.start_prob
        FROM user_squad us
        JOIN players p ON p.player_id = us.player_id
        JOIN predictions pr ON pr.player_id = p.player_id
        WHERE us.gw = :gw AND pr.gw = :gw
    """), dict(gw=gw)).fetchall()
    
    squad = [dict(r._mapping) for r in squad_rows]
    
    # 2. Get all viable candidates in the game for transfers
    candidate_rows = session.execute(text("""
        SELECT p.player_id, p.web_name AS name, p.position AS pos, p.now_cost AS price, pr.xp_mean AS xp
        FROM predictions pr
        JOIN players p ON p.player_id = pr.player_id
        WHERE pr.gw = :gw
    """), dict(gw=gw)).fetchall()
    
    candidates = [dict(r._mapping) for r in candidate_rows]
    
    # 3. Get team meta (bank/transfers)
    meta = session.execute(text("SELECT bank, free_transfers FROM team_meta WHERE gw = :gw"), dict(gw=gw)).fetchone()
    bank = float(meta.bank) if meta else 0.0
    
    return squad, candidates, bank

def run_pipeline(gw: int):
    session = get_session()
    print(f"--- Running FPL Agent v4 Optimizers for GW{gw} ---")
    
    squad, candidates, bank = get_squad_and_candidates(session, gw)
    
    if not squad:
        print("Error: No players found in user_squad for this GW. Make sure your team is populated!")
        return

    # --- 1. TRANSFER OPTIMIZATION ---
    transfer_plan = best_single_transfer(squad, candidates, bank)
    if transfer_plan:
        print(f"\n[TRANSFER RECOMMENDED]")
        print(f"OUT: {transfer_plan['out']['name']} (xP: {transfer_plan['out']['xp']})")
        print(f"IN:  {transfer_plan['in']['name']} (xP: {transfer_plan['in']['xp']})")
        print(f"Net Gain: +{transfer_plan['gain']} xP")
        
        # Log the recommendation to the database
        log_recommendation(gw, "transfer", transfer_plan)
    else:
        print("\n[TRANSFER] No transfers yield a positive expected points gain. Roll the transfer.")

    # --- 2. CAPTAINCY OPTIMIZATION ---
    # We pass the squad through the captaincy ranker to factor in p90 ceilings and start probabilities
    ranked_captains = rank_captains(squad)
    top_c = ranked_captains[0]
    top_vc = ranked_captains[1]
    
    print(f"\n[CAPTAINCY RECOMMENDED]")
    print(f"Captain: {top_c['name']} (Score: {top_c['captaincy_score']}, Ceiling: {top_c['p90']})")
    print(f"Vice-Captain: {top_vc['name']} (Score: {top_vc['captaincy_score']})")
    
    log_recommendation(gw, "captaincy", {"captain": top_c["name"], "vice": top_vc["name"]})
    
    session.close()
    print("\nRecommendations logged successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, required=True)
    args = parser.parse_args()
    run_pipeline(args.gw)