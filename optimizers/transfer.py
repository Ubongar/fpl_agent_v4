"""Single/multi-week transfer optimizer. Given current squad + budget + free
transfers, finds the swap(s) that maximize expected points gain minus any
points hit (-4/transfer beyond free allowance).

Risk adjustment: gains are computed on xp_mean * start_prob, not raw xp_mean.
Without this, the optimizer happily recommends an injured or benched player
who happens to have a high model mean -- the exact failure mode that made
"Enciso in for Wilson, +6.42" look suspicious in early testing. captaincy.py
already applies the same discount; this brings transfer.py in line.
"""


def best_single_transfer(squad: list[dict], candidates: list[dict], bank: float) -> dict:
    """squad/candidates: [{player_id, name, pos, price, xp_mean, start_prob}].
    Same-position swap only. Returns {"out","in","gain"} or None."""
    bank = float(bank)
    squad_ids = {p["player_id"] for p in squad}

    best = None
    for out_p in squad:
        out_price = float(out_p["price"])
        out_xp = float(out_p["xp_mean"]) * float(out_p.get("start_prob", 1.0))

        for in_p in candidates:
            if in_p["pos"] != out_p["pos"]:
                continue
            if in_p["player_id"] in squad_ids:
                continue
            if float(in_p["price"]) > out_price + bank:
                continue

            in_xp = float(in_p["xp_mean"]) * float(in_p.get("start_prob", 1.0))
            gain = in_xp - out_xp
            if best is None or gain > best["gain"]:
                best = {"out": out_p, "in": in_p, "gain": round(gain, 2)}

    return best


def evaluate_transfer_plan(gains: list[float], free_transfers: int, hit_cost: int = 4) -> float:
    """Net points impact of taking N transfers when only `free_transfers` are free."""
    paid = max(0, len(gains) - free_transfers)
    return round(sum(gains) - paid * hit_cost, 2)