"""Picks the optimal starting XI from your 15 for a given GW.
Constraints: 1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD, total 11.
Bench GK sits in BENCH_GK slot; outfield subs ordered by xp_mean."""
import pulp

FORMATION_LIMITS = {
    "GK":  (1, 1),
    "DEF": (3, 5),
    "MID": (2, 5),
    "FWD": (1, 3),
}
POSITIONS = ["GK", "DEF", "MID", "FWD"]


def _solve_xi(squad, objective_key="xp_mean"):
    prob = pulp.LpProblem("best_xi", pulp.LpMaximize)
    x = {p["player_id"]: pulp.LpVariable(f"x_{p['player_id']}", cat="Binary")
         for p in squad}

    prob += pulp.lpSum(float(p.get(objective_key, 0.0)) * x[p["player_id"]]
                        for p in squad)
    prob += pulp.lpSum(x[p["player_id"]] for p in squad) == 11

    for pos, (lo, hi) in FORMATION_LIMITS.items():
        pos_players = [p for p in squad if p["pos"] == pos]
        if not pos_players:
            return None
        prob += pulp.lpSum(x[p["player_id"]] for p in pos_players) >= lo
        prob += pulp.lpSum(x[p["player_id"]] for p in pos_players) <= hi

    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[prob.status] != "Optimal":
        return None
    return [p["player_id"] for p in squad if x[p["player_id"]].value() == 1]


def _bench_order(bench_players):
    gks = [p for p in bench_players if p["pos"] == "GK"]
    outfield = [p for p in bench_players if p["pos"] != "GK"]
    outfield.sort(key=lambda p: float(p.get("xp_mean", 0.0)), reverse=True)

    result = []
    if gks:
        result.append({**gks[0], "role": "BENCH_GK", "bench_order": 0})
    for i, p in enumerate(outfield[:3], start=1):
        result.append({**p, "role": f"BENCH_{i}", "bench_order": i})
    return result


def pick_best_xi(squad):
    if len(squad) < 11:
        raise ValueError(f"Need at least 11 players, got {len(squad)}")

    starter_ids = _solve_xi(squad)
    if starter_ids is None:
        raise ValueError(
            "No legal XI exists for this squad. Check that you have at least "
            "1 GK, 3 DEF, 2 MID, 1 FWD and at most 5 DEF, 5 MID, 3 FWD."
        )

    starters = [p for p in squad if p["player_id"] in starter_ids]
    bench = [p for p in squad if p["player_id"] not in starter_ids]

    starters.sort(key=lambda p: (POSITIONS.index(p["pos"]),
                                  -float(p.get("xp_mean", 0.0))))
    bench_ordered = _bench_order(bench)

    ranked = sorted(starters, key=lambda p: float(p.get("xp_mean", 0.0)),
                    reverse=True)
    captain = ranked[0] if ranked else None
    vice = ranked[1] if len(ranked) > 1 else None

    alternatives = []
    try:
        excluded = set()
        for _ in range(3):
            pool = [p for p in squad if p["player_id"] not in excluded]
            if len(pool) < 11:
                break
            alt_ids = _solve_xi(pool)
            if alt_ids is None:
                break
            alt_xi = [p for p in pool if p["player_id"] in alt_ids]
            alt_total = sum(float(p.get("xp_mean", 0.0)) for p in alt_xi)
            alternatives.append({
                "starting": alt_xi,
                "total_xp": round(alt_total, 2),
                "excluded_player_id": list(excluded)[-1] if excluded else None,
            })
            best_remaining = max(alt_xi, key=lambda p: float(p.get("xp_mean", 0.0)))
            excluded.add(best_remaining["player_id"])
    except Exception as e:
        print(f"[best_xi] alternatives skipped: {e!r}")

    total_xp = sum(float(p.get("xp_mean", 0.0)) for p in starters)

    return {
        "starting": [{**p, "role": "START"} for p in starters],
        "bench": bench_ordered,
        "captain": captain,
        "vice": vice,
        "total_xp": round(total_xp, 2),
        "alternatives": alternatives,
    }
    