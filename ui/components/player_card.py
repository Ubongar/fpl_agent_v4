import streamlit as st

POS_COLOR = {"GK": "#f7d13d", "DEF": "#00ff87",
             "MID": "#04f5ff", "FWD": "#e90052"}


def render_player_card(p, compact=False):
    pos = p.get("pos", "?")
    color = POS_COLOR.get(pos, "#666")
    name = p.get("name", "Unknown")
    xp = p.get("xp_mean", 0.0)
    price = p.get("price", 0.0)
    sp = p.get("start_prob", 1.0)
    p10, p90 = p.get("p10"), p.get("p90")

    injury_badge = ""
    if isinstance(sp, (int, float)) and sp <= 0.0:
        injury_badge = " 🚑"

    range_html = ""
    if p10 is not None and p90 is not None:
        range_html = (f"<div style='font-size:0.75em;color:#888'>"
                      f"p10–p90: {float(p10):.1f} – {float(p90):.1f}</div>")

    st.markdown(f"""
    <div style="border:1px solid #333;border-radius:8px;padding:10px;
                background:#0e1117;margin-bottom:8px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="background:{color};color:#000;font-weight:700;
                         font-size:0.7em;padding:2px 6px;border-radius:4px;">{pos}</span>
            <span style="font-size:0.8em;color:#aaa;">£{float(price):.1f}m</span>
        </div>
        <div style="font-weight:600;margin-top:6px;font-size:0.95em;">{name}{injury_badge}</div>
        <div style="font-size:0.85em;color:#bbb;">xP: <b>{float(xp):.2f}</b></div>
        {range_html}
    </div>
    """, unsafe_allow_html=True)