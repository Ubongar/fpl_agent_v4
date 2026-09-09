"""Streamlit command center -- wires together every layer for interactive use."""
import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="FPL Agent v3", page_icon="⚽", layout="wide")
st.title("⚽ FPL Agent v3 — Predictive + Optimization Engine")

tab_overview, tab_predictions, tab_transfers, tab_wildcard, tab_captain, tab_chips, tab_track, tab_ask = st.tabs(
    ["Overview", "Predictions", "Transfers", "Wildcard", "Captaincy", "Chips", "Tracking", "Ask the Agent"]
)

with tab_overview:
    st.subheader("System status")
    st.caption("Wire this to live DB queries once Postgres is populated via ingestion/fpl_source.py")
    st.info("Run `python ops/retrain_job.py` first to populate today's snapshot.")

with tab_predictions:
    st.subheader("Player expected points (models.expected_points)")
    st.caption("Replace with a live query against the `predictions` table.")
    demo = pd.DataFrame({"player": ["Palmer", "Haaland", "Gabriel"], "xp_mean": [7.2, 8.9, 5.1],
                         "p10": [1.0, 2.0, 0.5], "p90": [14.0, 16.0, 9.0]})
    st.dataframe(demo, use_container_width=True)
    fig = px.bar(demo, x="player", y="xp_mean", error_y=demo["p90"] - demo["xp_mean"],
                 error_y_minus=demo["xp_mean"] - demo["p10"], title="xP with 10-90 percentile range")
    st.plotly_chart(fig, use_container_width=True)

with tab_transfers:
    st.subheader("Transfer optimizer")
    st.caption("Calls optimizers/transfer.py against your current squad + candidate pool.")

with tab_wildcard:
    st.subheader("Wildcard optimizer (ILP)")
    budget = st.slider("Budget (£m)", 80.0, 110.0, 100.0)
    st.caption("Calls optimizers/wildcard.optimize_wildcard(pool, budget=...)")

with tab_captain:
    st.subheader("Captaincy ranking")
    st.caption("Calls optimizers/captaincy.rank_captains() -- ranks by ceiling-weighted score, not just mean.")

with tab_chips:
    st.subheader("Chip timing")
    st.caption("Calls optimizers/chip.py scoring functions across the fixture list.")

with tab_track:
    st.subheader("Recommendation tracking")
    st.caption("Live performance of past recommendations vs actual outcomes (ops/tracking.py).")

with tab_ask:
    st.subheader("Ask the agent")
    q = st.text_input("Ask about any recommendation above:")
    if q:
        st.caption("Wire this input into agent/llm_agent.explain_recommendation(...)")
