import streamlit as st

POS_ROW = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}


def render_pitch(starting, captain, vice):
    cap_id = captain["player_id"] if captain else None
    vc_id = vice["player_id"] if vice else None

    rows = {0: [], 1: [], 2: [], 3: []}
    for p in starting:
        rows[POS_ROW[p["pos"]]].append(p)

    st.markdown(
        "<div style='background:linear-gradient(#0e4a2a,#0a3d23);"
        "border-radius:12px;padding:16px;margin-bottom:16px;'>",
        unsafe_allow_html=True,
    )
    for row_idx in [3, 2, 1, 0]:
        players = rows[row_idx]
        if not players:
            continue
        cols = st.columns(len(players))
        for i, p in enumerate(players):
            badge = ""
            if p["player_id"] == cap_id:
                badge = " (C)"
            elif p["player_id"] == vc_id:
                badge = " (V)"
            with cols[i]:
                st.markdown(
                    f"<div style='text-align:center;background:rgba(0,0,0,0.4);"
                    f"border-radius:8px;padding:8px;margin:4px 0;'>"
                    f"<div style='font-weight:700;color:#fff;font-size:0.9em;'>"
                    f"{p['name']}{badge}</div>"
                    f"<div style='color:#00ff87;font-size:0.8em;'>"
                    f"{p['xp_mean']:.1f} xP</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
    st.markdown("</div>", unsafe_allow_html=True)