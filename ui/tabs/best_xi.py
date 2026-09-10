import streamlit as st
from ui.state import get_session_state
from ui.components.pitch_view import render_pitch
from ui.components.player_card import render_player_card
from llm.client import explain_pick, is_enabled


def render():
    st.header("Best XI")
    state = get_session_state()
    if not state.loaded or not state.best_xi:
        st.info("Load a gameweek to compute your Best XI.")
        return

    xi = state.best_xi
    c1, c2, c3 = st.columns(3)
    c1.metric("Total xP", f"{xi['total_xp']:.2f}")
    c2.metric("Captain", xi["captain"]["name"] if xi["captain"] else "—")
    c3.metric("Vice", xi["vice"]["name"] if xi["vice"] else "—")

    st.divider()
    render_pitch(xi["starting"], xi["captain"], xi["vice"])

    st.subheader("Bench (substitution order)")
    bcols = st.columns(4)
    for i, p in enumerate(xi["bench"]):
        with bcols[i % 4]:
            render_player_card(p, compact=True)

    if is_enabled():
        if st.button("🧠 Explain this XI", key="explain_xi"):
            with st.spinner("Asking the model…"):
                ctx = {
                    "formation_counts": {
                        pos: sum(1 for p in xi["starting"] if p["pos"] == pos)
                        for pos in ["GK", "DEF", "MID", "FWD"]
                    },
                    "total_xp": xi["total_xp"],
                    "captain": {"name": xi["captain"]["name"],
                                "xp_mean": xi["captain"]["xp_mean"],
                                "p90": xi["captain"]["p90"]},
                }
                text = explain_pick("best_xi", ctx)
                if text:
                    st.info(text)

    if xi["alternatives"]:
        with st.expander(f"Alternative XIs ({len(xi['alternatives'])})"):
            for i, alt in enumerate(xi["alternatives"], 1):
                st.markdown(f"**Alt {i}** — total xP = {alt['total_xp']}")
                st.write(", ".join(p["name"] for p in alt["starting"]))
                st.divider()