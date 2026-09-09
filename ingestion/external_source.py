"""Multi-source ingestion stub. Add real xG providers (Understat/FBref) here.
Each source should return a DataFrame keyed by player name/team for fuzzy-join
against the FPL player table, since external sources rarely share FPL's IDs."""
import pandas as pd

def fetch_external_xg(source: str = "understat") -> pd.DataFrame:
    # TODO: implement real scraping/API call per source.
    # Must return columns: [player_name, team, xg90, xa90, source]
    raise NotImplementedError(f"Source '{source}' not yet wired up.")

def fuzzy_join_to_players(external_df: pd.DataFrame, players_df: pd.DataFrame) -> pd.DataFrame:
    """Name-based join since external sources don't share FPL element IDs.
    Use rapidfuzz or similar for production; placeholder does exact match only."""
    return players_df.merge(external_df, left_on="web_name", right_on="player_name", how="left")
