"""Single/multi-week transfer optimizer. Given current squad + budget + free
transfers, finds the swap(s) that maximize expected points gain minus any
points hit (-4/transfer beyond free allowance)."""

def best_single_transfer(squad: list[dict], candidates: list[dict], bank: float) -> dict:
    """squad/candidates: [{player_id, name, pos, price, xp}]. Same-position swap only."""
    best = None
    for out_p in squad:
        affordable = [c for c in candidates
                      if c["pos"] == out_p["pos"] and c["price"] <= out_p["price"] + bank
                      and c["player_id"] not in {p["player_id"] for p in squad}]
        for in_p in affordable:
            gain = in_p["xp"] - out_p["xp"]
            if best is None or gain > best["gain"]:
                best = {"out": out_p, "in": in_p, "gain": round(gain, 2)}
    return best

def evaluate_transfer_plan(gains: list[float], free_transfers: int, hit_cost: int = 4) -> float:
    """Net points impact of taking N transfers when only `free_transfers` are free."""
    paid = max(0, len(gains) - free_transfers)
    return round(sum(gains) - paid * hit_cost, 2)
