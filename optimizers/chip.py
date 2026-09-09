"""Chip timing optimizer (Bench Boost / Triple Captain / Free Hit).
Heuristic v1: score each upcoming GW on fixture swing + squad-wide xP, since
this requires forward fixture data more than complex modeling."""

def score_bench_boost_weeks(squad_bench_xp_by_gw: dict[int, float]) -> list[tuple[int, float]]:
    """Best week = highest combined bench xP (all 4 bench players contribute)."""
    return sorted(squad_bench_xp_by_gw.items(), key=lambda kv: kv[1], reverse=True)

def score_triple_captain_weeks(top_captain_xp_by_gw: dict[int, float]) -> list[tuple[int, float]]:
    """Best week = highest single-player xP ceiling (favor DGWs and elite fixtures)."""
    return sorted(top_captain_xp_by_gw.items(), key=lambda kv: kv[1], reverse=True)

def score_free_hit_weeks(blank_gw_squad_players_missing: dict[int, int]) -> list[tuple[int, int]]:
    """Best week = most players from your squad blanking (BGW), sorted descending."""
    return sorted(blank_gw_squad_players_missing.items(), key=lambda kv: kv[1], reverse=True)
