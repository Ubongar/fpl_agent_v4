"""Single-transfer optimizer. xp_mean is already risk-adjusted."""


def best_single_transfer(squad, candidates, bank, max_per_position=3):
    bank = float(bank)
    squad_ids = {p["player_id"] for p in squad}

    club_count = {}
    if all("team_id" in p for p in squad):
        for p in squad:
            club_count[p["team_id"]] = club_count.get(p["team_id"], 0) + 1

    best = None
    for out_p in squad:
        out_price = float(out_p["price"])
        out_xp = float(out_p["xp_mean"])

        for in_p in candidates:
            if in_p["pos"] != out_p["pos"]:
                continue
            if in_p["player_id"] in squad_ids:
                continue
            if float(in_p["price"]) > out_price + bank:
                continue
            if float(in_p.get("start_prob", 1.0)) <= 0.0:
                continue
            if club_count and "team_id" in in_p:
                if in_p["team_id"] != out_p.get("team_id"):
                    if club_count.get(in_p["team_id"], 0) >= max_per_position:
                        continue

            gain = float(in_p["xp_mean"]) - out_xp
            if best is None or gain > best["gain"]:
                best = {"out": out_p, "in": in_p, "gain": round(gain, 2)}
    return best


def evaluate_transfer_plan(gains, free_transfers, hit_cost=4):
    paid = max(0, len(gains) - free_transfers)
    return round(sum(gains) - paid * hit_cost, 2)