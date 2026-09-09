"""Full 15-man squad rebuild under budget using ILP (PuLP) -- maximizes total
xP subject to: budget, exactly 2 GK/5 DEF/5 MID/3 FWD, max 3 players per club."""
import pulp

def optimize_wildcard(pool: list[dict], budget: float = 100.0, max_per_club: int = 3) -> list[dict]:
    """pool: [{player_id, name, pos, club, price, xp}]"""
    prob = pulp.LpProblem("wildcard", pulp.LpMaximize)
    x = {p["player_id"]: pulp.LpVariable(f"x_{p['player_id']}", cat="Binary") for p in pool}

    prob += pulp.lpSum(p["xp"] * x[p["player_id"]] for p in pool)
    prob += pulp.lpSum(p["price"] * x[p["player_id"]] for p in pool) <= budget

    for pos, n in {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}.items():
        prob += pulp.lpSum(x[p["player_id"]] for p in pool if p["pos"] == pos) == n

    for club in {p["club"] for p in pool}:
        prob += pulp.lpSum(x[p["player_id"]] for p in pool if p["club"] == club) <= max_per_club

    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    return [p for p in pool if x[p["player_id"]].value() == 1]
