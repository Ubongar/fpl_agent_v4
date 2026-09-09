"""Double/Blank gameweek handling. DGW players get summed xP across both
fixtures (not doubled blindly -- fixture difficulty differs per leg).
BGW players get zeroed and must be temporarily replaced in optimizer runs."""

def adjust_for_dgw(player_xp_per_fixture: dict[int, list[float]]) -> dict[int, float]:
    """player_xp_per_fixture: {player_id: [xp_leg1, xp_leg2, ...]}"""
    return {pid: round(sum(legs), 2) for pid, legs in player_xp_per_fixture.items()}

def flag_bgw_players(squad: list[dict], fixture_count_by_player: dict[int, int]) -> list[dict]:
    return [p for p in squad if fixture_count_by_player.get(p["player_id"], 1) == 0]
