"""Session-scoped state for the Streamlit app."""
from dataclasses import dataclass, field
from typing import Optional
import streamlit as st
from db.connection import get_session
from sqlalchemy import text
from optimizers.run_all import run_pipeline


STATE_KEY = "fpl_session"


@dataclass
class FPLSession:
    gw: int = 4
    team_id: Optional[int] = None
    squad: list = field(default_factory=list)
    best_xi: Optional[dict] = None
    transfer: Optional[dict] = None
    captains: list = field(default_factory=list)
    bank: float = 0.0
    loaded: bool = False
    error: Optional[str] = None


def get_session_state() -> FPLSession:
    if STATE_KEY not in st.session_state:
        st.session_state[STATE_KEY] = FPLSession()
    return st.session_state[STATE_KEY]


def load_gw(gw, log=False):
    s = get_session_state()
    s.gw = gw
    s.error = None
    try:
        result = run_pipeline(gw, log=log)
        s.squad = result["squad"]
        s.best_xi = result["best_xi"]
        s.transfer = result["transfer"]
        s.captains = result["captains"]
        s.bank = result["bank"]
        s.loaded = True
    except Exception as e:
        s.error = str(e)
        s.loaded = False


def latest_gw_with_data() -> int:
    session = get_session()
    try:
        row = session.execute(text(
            "SELECT MAX(gw) AS gw FROM predictions WHERE player_id IN "
            "(SELECT player_id FROM user_squad)"
        )).fetchone()
        return int(row.gw) if row and row.gw is not None else 4
    finally:
        session.close()