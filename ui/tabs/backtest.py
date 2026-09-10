import streamlit as st
import pandas as pd
from db.connection import get_session
from sqlalchemy import text
from ui.components.charts import mae_over_time


def render():
    st.header("Backtest")
    st.caption("Walk-forward evaluation. Run "
               "`python -m validation.backtest --start-gw 3 --end-gw 3 --rerun` "
               "to populate.")

    session = get_session()
    try:
        rows = session.execute(text("""
            SELECT model_version, gw, n_players, mae, rmse, spearman,
                   captain_hit, captain_predicted_pts, captain_actual_pts, oracle_pts
            FROM backtest_results ORDER BY gw
        """)).fetchall()
    finally:
        session.close()

    if not rows:
        st.info(
            "No backtest results yet. With GW1-3 complete, you can backtest "
            "GW3 only:\n\n"
            "```bash\npython -m validation.backtest --start-gw 3 --end-gw 3 --rerun\n```"
        )
        return

    df = pd.DataFrame([dict(r._mapping) for r in rows])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("GWs backtested", len(df))
    c2.metric("Mean MAE", f"{df['mae'].mean():.3f}")
    c3.metric("Mean Spearman", f"{df['spearman'].mean():.3f}")
    c4.metric("Captain hit rate", f"{df['captain_hit'].mean() * 100:.0f}%")

    st.subheader("MAE / RMSE over time")
    st.plotly_chart(mae_over_time(df), use_container_width=True)

    st.subheader("Captaincy: model vs oracle")
    df["regret"] = df["oracle_pts"] - df["captain_actual_pts"]
    st.dataframe(df[["gw", "captain_predicted_pts", "captain_actual_pts",
                     "oracle_pts", "regret"]],
                 use_container_width=True, hide_index=True)
    st.caption(f"Mean regret per GW: **{df['regret'].mean():.2f} points**")