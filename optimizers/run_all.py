"""Master pipeline: squad -> Best XI -> transfer -> captaincy -> logs.
Prints a stage line before each step so you can see where it is."""
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from db.connection import get_session
from sqlalchemy import text

from optimizers.transfer import best_single_transfer
from optimizers.captaincy import rank_captains
from optimizers.best_xi import pick_best_xi
from ops.tracking import log_recommendation


REQUIRED_KEYS = {"player_id", "name", "pos", "price", "xp_mean",
                 "p10", "p50", "p90", "start_prob"}


def _log(msg):
    """Timestamped stage log so long runs are visibly alive."""
    print(f"[run_all] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def _to_float(d, keys):
    for k in keys:
        if k in d and d[k] is not None:
            d[k] = float(d[k])
    return d


def display_name(p):
    first = (p.get("first_name") or "").strip()
    second = (p.get("second_name") or "").strip()
    full = f"{first} {second}".strip()
    return full if full else (p.get("name") or "Unknown")


def load_squad(session, gw):
    rows = session.execute(text("""
        SELECT p.player_id, p.web_name AS name, p.first_name, p.second_name,
               p.team_id, p.position AS pos, p.now_cost AS price,
               pr.xp_mean, pr.xp_p10 AS p10, pr.xp_p50 AS p50,
               pr.xp_p90 AS p90, pr.start_prob
        FROM user_squad us
        JOIN players p ON p.player_id = us.player_id
        JOIN predictions pr ON pr.player_id = p.player_id
        WHERE us.gw = :gw AND pr.gw = :gw
    """), dict(gw=gw)).fetchall()
    squad = []
    for r in rows:
        d = _to_float(dict(r._mapping),
                      ("price", "xp_mean", "p10", "p50", "p90", "start_prob"))
        missing = REQUIRED_KEYS - d.keys()
        if missing:
            raise KeyError(f"Squad row {d.get('player_id')} missing {sorted(missing)}")
        squad.append(d)
    return squad


def load_candidates(session, gw):
    rows = session.execute(text("""
        SELECT p.player_id, p.web_name AS name, p.first_name, p.second_name,
               p.team_id, p.position AS pos, p.now_cost AS price,
               pr.xp_mean, pr.start_prob
        FROM predictions pr
        JOIN players p ON p.player_id = pr.player_id
        WHERE pr.gw = :gw
    """), dict(gw=gw)).fetchall()
    return [_to_float(dict(r._mapping), ("price", "xp_mean", "start_prob"))
            for r in rows]


def load_bank(session, gw):
    row = session.execute(
        text("SELECT bank FROM team_meta WHERE gw = :gw"), dict(gw=gw)
    ).fetchone()
    return float(row.bank) if row else 0.0


def run_pipeline(gw, log=True, verbose=True):
    session = get_session()
    try:
        if verbose:
            _log(f"GW{gw}: loading squad from user_squad…")
        squad = load_squad(session, gw)
        if not squad:
            raise RuntimeError(
                f"No squad found in user_squad for GW{gw}. "
                f"Run import_squad.py first or check user_squad.gw."
            )
        if verbose:
            _log(f"GW{gw}: squad has {len(squad)} players.")

        if verbose:
            _log(f"GW{gw}: loading candidate pool from predictions…")
        candidates = load_candidates(session, gw)
        if verbose:
            _log(f"GW{gw}: {len(candidates)} candidates in pool.")

        bank = load_bank(session, gw)
        if verbose:
            _log(f"GW{gw}: bank = £{bank:.1f}m.")

        # --- Best XI (ILP) ---
        if verbose:
            _log("solving Best XI (ILP)…")
        t0 = time.time()
        best_xi = pick_best_xi(squad)
        if verbose:
            _log(f"Best XI solved in {time.time() - t0:.2f}s "
                 f"(total xP = {best_xi['total_xp']}).")

        # --- Transfer ---
        if verbose:
            _log(f"scanning {len(squad) * len(candidates)} transfer pairs…")
        t0 = time.time()
        transfer_plan = best_single_transfer(squad, candidates, bank)
        if verbose:
            if transfer_plan:
                _log(f"best transfer found in {time.time() - t0:.2f}s: "
                     f"{display_name(transfer_plan['out'])} → "
                     f"{display_name(transfer_plan['in'])} "
                     f"(+{transfer_plan['gain']} xP).")
            else:
                _log(f"no positive-gain transfer ({time.time() - t0:.2f}s).")

        # --- Captaincy ---
        if verbose:
            _log("ranking captaincy candidates…")
        ranked_captains = rank_captains(squad)
        if verbose:
            _log(f"top captain: {display_name(ranked_captains[0])} "
                 f"(score {ranked_captains[0]['captaincy_score']}).")

        # --- Log to DB ---
        if log:
            if verbose:
                _log("writing recommendations to DB…")
            if transfer_plan:
                log_recommendation(gw, "transfer", {
                    "out_id": transfer_plan["out"]["player_id"],
                    "out_name": display_name(transfer_plan["out"]),
                    "in_id": transfer_plan["in"]["player_id"],
                    "in_name": display_name(transfer_plan["in"]),
                    "gain": transfer_plan["gain"],
                }, session=session)
            if len(ranked_captains) >= 2:
                c, vc = ranked_captains[0], ranked_captains[1]
                log_recommendation(gw, "captaincy", {
                    "captain_id": c["player_id"], "captain_name": display_name(c),
                    "vice_id": vc["player_id"], "vice_name": display_name(vc),
                }, session=session)

        if verbose:
            _log("pipeline complete.")

        return {
            "squad": squad,
            "best_xi": best_xi,
            "transfer": transfer_plan,
            "captains": ranked_captains,
            "bank": bank,
            "gw": gw,
        }
    finally:
        session.close()


def _print_result(result):
    print(f"\n--- FPL Agent v5 -- GW{result['gw']} ---\n")
    xi = result["best_xi"]
    print(f"[BEST XI] total xP = {xi['total_xp']}")
    print(f"  Captain:      {display_name(xi['captain'])}")
    print(f"  Vice-Captain: {display_name(xi['vice'])}")
    print("  Starting:")
    for p in xi["starting"]:
        print(f"    {p['pos']:>3}  {display_name(p):<25}  xP={p['xp_mean']}")
    print("  Bench:")
    for p in xi["bench"]:
        print(f"    {p['role']:<10} {display_name(p):<25}  xP={p['xp_mean']}")

    t = result["transfer"]
    print("\n[TRANSFER]")
    if t:
        print(f"  OUT: {display_name(t['out'])} (xP={t['out']['xp_mean']})")
        print(f"  IN:  {display_name(t['in'])} (xP={t['in']['xp_mean']})")
        print(f"  Net: +{t['gain']}")
    else:
        print("  No positive-gain swap. Roll the transfer.")

    print("\n[CAPTAINCY top 5]")
    for c in result["captains"][:5]:
        print(f"  {display_name(c):<25} score={c['captaincy_score']} "
              f"p90={c['p90']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, required=True)
    parser.add_argument("--quiet", action="store_true",
                         help="Suppress stage-by-stage progress logs.")
    args = parser.parse_args()
    result = run_pipeline(args.gw, log=True, verbose=not args.quiet)
    _print_result(result)