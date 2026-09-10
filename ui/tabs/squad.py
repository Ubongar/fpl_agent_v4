import streamlit as st
from ui.state import get_session_state
from ui.components.player_card import render_player_card


def render():
    st.header("Your Squad")
    state = get_session_state()
    if not state.loaded:
        st.info("Load a gameweek from the sidebar to see your squad.")
        return

    st.caption(f"GW{state.gw} · Bank: £{state.bank:.1f}m · "
               f"{len(state.squad)} players")

    by_pos = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for p in state.squad:
        by_pos[p["pos"]].append(p)

    for pos in ["GK", "DEF", "MID", "FWD"]:
        players = by_pos[pos]
        if not players:
            continue
        st.subheader(f"{pos} ({len(players)})")
        cols = st.columns(min(len(players), 5))
        for i, p in enumerate(players):
            with cols[i % len(cols)]:
                render_player_card(p)