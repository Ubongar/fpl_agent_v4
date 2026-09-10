"""FPL Agent v5 UI. Run:  streamlit run ui/app.py"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from ui.state import get_session_state, load_gw, latest_gw_with_data
from ui.tabs import squad, best_xi, transfers, captain, fixtures, backtest
from llm.client import is_enabled as llm_enabled

st.set_page_config(page_title="FPL Agent v5", page_icon="⚽",
                   layout="wide", initial_sidebar_state="expanded")

st.sidebar.title("⚽ FPL Agent v5")
st.sidebar.caption("Model-backed FPL optimiser")

default_gw = latest_gw_with_data()
state = get_session_state()

gw_input = st.sidebar.number_input("Gameweek", min_value=1, max_value=38,
                                    value=state.gw or default_gw, step=1)
col_a, col_b = st.sidebar.columns(2)
if col_a.button("Load GW", use_container_width=True, type="primary"):
    with st.spinner(f"Loading GW{gw_input}…"):
        load_gw(int(gw_input))
    st.rerun()
if col_b.button("Reload", use_container_width=True):
    with st.spinner("Reloading…"):
        load_gw(int(gw_input))
    st.rerun()

state = get_session_state()
if state.error:
    st.sidebar.error(f"⚠️ {state.error}")
elif state.loaded:
    st.sidebar.success(f"✓ GW{state.gw} loaded · {len(state.squad)} players")
else:
    st.sidebar.info("Click **Load GW** to start.")

st.sidebar.divider()
st.sidebar.caption(
    f"LLM: {'✅ enabled' if llm_enabled() else '⬜ disabled (set OPENAI_API_KEY)'}"
)
st.sidebar.caption("Model: v5")

t1, t2, t3, t4, t5, t6 = st.tabs([
    "🏠 Squad", "🎯 Best XI", "🔄 Transfers", "👑 Captain",
    "📅 Fixtures", "📊 Backtest",
])
with t1: squad.render()
with t2: best_xi.render()
with t3: transfers.render()
with t4: captain.render()
with t5: fixtures.render()
with t6: backtest.render()