import streamlit as st
from ui.state import get_session_state
from ui.components.player_card import render_player_card
from llm.client import explain_pick, is_enabled


def render():
    st.header("Transfer Suggestions")
    state = get_session_state()
    if not state.loaded:
        st.info("Load a gameweek first.")
        return

    t = state.transfer
    if not t:
        st.success("✅ No positive-gain transfer. Roll your FT.")
        return

    st.subheader("Top recommendation")
    c1, c2, c3 = st.columns(3)
    c1.metric("Gain", f"+{t['gain']:.2f} xP")
    bank_after = state.bank - (t["in"]["price"] - t["out"]["price"])
    c2.metric("Bank after", f"£{bank_after:.1f}m")
    c3.metric("Position", t["out"]["pos"])

    col_out, col_arrow, col_in = st.columns([5, 1, 5])
    with col_out:
        st.markdown("**OUT**")
        render_player_card(t["out"])
    with col_arrow:
        st.markdown("<div style='text-align:center;font-size:2em;"
                    "padding-top:3em'>→</div>", unsafe_allow_html=True)
    with col_in:
        st.markdown("**IN**")
        render_player_card(t["in"])

    if is_enabled():
        if st.button("🧠 Explain this transfer", key="explain_transfer"):
            with st.spinner("Asking the model…"):
                ctx = {
                    "out": {"name": t["out"]["name"],
                            "xp_mean": t["out"]["xp_mean"],
                            "price": t["out"]["price"],
                            "pos": t["out"]["pos"]},
                    "in":  {"name": t["in"]["name"],
                            "xp_mean": t["in"]["xp_mean"],
                            "price": t["in"]["price"],
                            "pos": t["in"]["pos"]},
                    "net_gain_xp": t["gain"],
                    "bank_after": bank_after,
                }
                text = explain_pick("transfer", ctx)
                if text:
                    st.info(text)