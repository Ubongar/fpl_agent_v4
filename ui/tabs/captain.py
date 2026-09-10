import streamlit as st
from ui.state import get_session_state
from ui.components.charts import captaincy_bar
from llm.client import explain_pick, is_enabled


def render():
    st.header("Captaincy Rankings")
    state = get_session_state()
    if not state.loaded or not state.captains:
        st.info("Load a gameweek first.")
        return

    st.caption("Score = 0.4·xP + 0.4·p90 + 0.2·p10. Ceiling-heavy.")

    top = state.captains[:8]
    for i, c in enumerate(top, 1):
        with st.container(border=True):
            cols = st.columns([4, 1, 1, 1, 1])
            cols[0].markdown(f"**{i}. {c['name']}**  \n`{c['pos']}` · £{c['price']}m")
            cols[1].metric("Score", f"{c['captaincy_score']:.2f}")
            cols[2].metric("xP", f"{c['xp_mean']:.2f}")
            cols[3].metric("p90", f"{c['p90']:.2f}")
            cols[4].metric("p10", f"{c['p10']:.2f}")

    st.divider()
    st.plotly_chart(captaincy_bar(top), use_container_width=True)

    if is_enabled():
        if st.button("🧠 Explain top pick", key="explain_captain"):
            with st.spinner("Asking the model…"):
                c = top[0]
                ctx = {
                    "name": c["name"],
                    "captaincy_score": c["captaincy_score"],
                    "xp_mean": c["xp_mean"], "p10": c["p10"], "p90": c["p90"],
                    "start_prob": c["start_prob"],
                    "runner_up": {"name": top[1]["name"],
                                  "captaincy_score": top[1]["captaincy_score"]}
                                  if len(top) > 1 else None,
                }
                text = explain_pick("captain", ctx)
                if text:
                    st.info(text)