import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from db.connection import get_session
from sqlalchemy import text
from ui.state import get_session_state


@st.cache_data(ttl=600)
def _load_fdr_grid(current_gw):
    session = get_session()
    try:
        rows = session.execute(text("""
            SELECT t.team_id, t.short_name, f.gw,
                   CASE WHEN f.home_team_id = t.team_id
                        THEN f.away_team_id ELSE f.home_team_id END AS opp_id,
                   CASE WHEN f.home_team_id = t.team_id
                        THEN TRUE ELSE FALSE END AS is_home
            FROM teams t
            JOIN fixtures f ON (f.home_team_id = t.team_id
                                OR f.away_team_id = t.team_id)
            WHERE f.gw BETWEEN :gw AND :gw + 5
            ORDER BY t.short_name, f.gw
        """), dict(gw=current_gw)).fetchall()

        ratings = session.execute(text("""
            SELECT DISTINCT ON (team_id) team_id, attack_home, attack_away,
                   defence_home, defence_away
            FROM team_strength ORDER BY team_id, gw DESC
        """)).fetchall()
        rmap = {r.team_id: r for r in ratings}

        records = []
        for r in rows:
            opp = rmap.get(r.opp_id)
            me = rmap.get(r.team_id)
            if opp and me:
                opp_def = float(opp.defence_away if r.is_home else opp.defence_home)
                my_att = float(me.attack_home if r.is_home else me.attack_away)
                raw = opp_def / max(my_att, 0.1)
                fdr = max(1, min(5, round(raw * 2.5)))
            else:
                fdr = 3
            records.append({"team": r.short_name, "gw": r.gw, "fdr": fdr})
        return pd.DataFrame(records)
    finally:
        session.close()


def render():
    st.header("Fixture Difficulty (next 6 GWs)")
    state = get_session_state()
    gw = state.gw or 4

    df = _load_fdr_grid(gw)
    if df.empty:
        st.info("No fixtures loaded for the next 6 GWs.")
        return

    pivot = df.pivot_table(index="team", columns="gw", values="fdr", aggfunc="min")
    pivot = pivot.reindex(sorted(pivot.index))

    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=[f"GW{c}" for c in pivot.columns],
        y=pivot.index,
        colorscale=[[0, "#00ff87"], [0.5, "#f7d13d"], [1, "#e90052"]],
        zmin=1, zmax=5,
        text=pivot.values.astype(int), texttemplate="%{text}",
        showscale=True, colorbar=dict(title="Difficulty"),
    ))
    fig.update_layout(height=max(400, 22 * len(pivot)),
                      margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("1 = easiest · 5 = hardest · computed from team_strength ratings.")