"""Streamlit command center -- wires together every layer for interactive use."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="FPL Agent v4", page_icon="⚽", layout="wide")
st.title("⚽ FPL Agent v4 — Predictive + Optimization Engine")

tab_overview, tab_predictions, tab_transfers, tab_wildcard, tab_captain, tab_chips, tab_track, tab_ask = st.tabs(
    ["Overview", "Predictions", "Transfers", "Wildcard", "Captaincy", "Chips", "Tracking", "Ask the Agent"]
)

with tab_overview:
    st.subheader("System status")
    try:
        from db.connection import get_session
        from sqlalchemy import text
        session = get_session()
        counts = {
            "Teams": session.execute(text("SELECT COUNT(*) FROM teams")).scalar(),
            "Players": session.execute(text("SELECT COUNT(*) FROM players")).scalar(),
            "Finished fixtures": session.execute(text(
                "SELECT COUNT(*) FROM fixtures WHERE home_goals IS NOT NULL")).scalar(),
            "Player-GW rows": session.execute(text("SELECT COUNT(*) FROM player_gw_points")).scalar(),
            "Team ratings computed": session.execute(text(
                "SELECT COUNT(DISTINCT team_id) FROM team_strength")).scalar(),
        }
        latest_gw = session.execute(text(
            "SELECT MAX(gw) FROM player_gw_points")).scalar()
        session.close()

        cols = st.columns(len(counts))
        for col, (label, val) in zip(cols, counts.items()):
            col.metric(label, val or 0)

        if not counts["Players"]:
            st.warning("No players ingested yet. Run `python ops/retrain_job.py` first.")
        elif not counts["Player-GW rows"]:
            st.warning("Players ingested but no per-GW history yet. Run "
                       "`python -m ingestion.historical_backfill`.")
        elif not counts["Team ratings computed"]:
            st.warning("No team_strength ratings yet. Run `python -m models.train_team_strength`.")
        else:
            st.success(f"Data pipeline populated through GW{latest_gw}.")
    except Exception as e:
        st.error(f"Could not query database: {e}")

with tab_predictions:
    st.subheader("Player expected points")
    st.caption("Live query against player_gw_points -- computes rolling average as a "
               "simple stand-in until the full expected_points model is wired with real "
               "team_strength/dixon_coles data per fixture.")
    try:
        from db.connection import get_session
        from sqlalchemy import text
        session = get_session()
        rows = session.execute(text("""
            SELECT p.web_name AS player, pg.gw, pg.gw_points, pg.minutes
            FROM player_gw_points pg
            JOIN players p ON p.player_id = pg.player_id
            ORDER BY p.web_name, pg.gw
        """)).fetchall()
        session.close()

        if not rows:
            st.warning("No data in player_gw_points yet. Run historical_backfill or "
                       "ops/retrain_job.py first.")
        else:
            df = pd.DataFrame(rows, columns=["player", "gw", "gw_points", "minutes"])
            summary = df.groupby("player").agg(
                avg_points=("gw_points", "mean"),
                gws_played=("gw", "count"),
                avg_minutes=("minutes", "mean"),
            ).reset_index().sort_values("avg_points", ascending=False).head(20)
            st.dataframe(summary, use_container_width=True)
            fig = px.bar(summary, x="player", y="avg_points",
                         title="Rolling average points per GW (top 20, real data)")
            st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Could not query database: {e}")

with tab_transfers:
    st.subheader("Squad & Transfer optimizer")
    try:
        from db.connection import get_session
        from sqlalchemy import text
        from optimizers.transfer import best_single_transfer, evaluate_transfer_plan
        session = get_session()

        latest_gw = session.execute(text("SELECT MAX(gw) FROM user_squad")).scalar()
        all_players = session.execute(text(
            "SELECT p.player_id, p.web_name, p.position, p.now_cost, t.short_name AS club "
            "FROM players p JOIN teams t ON t.team_id = p.team_id")).fetchall()

        with st.expander("Set / update your squad", expanded=(latest_gw is None)):
            from ui.pitch import render_squad_builder

            players_df = pd.DataFrame([{
                "player_id": int(p.player_id),
                "name": p.web_name,
                "pos": p.position,
                "club": p.club,
                "price": float(p.now_cost),
            } for p in all_players])

            selection = render_squad_builder(players_df, key_prefix="sb")

            bank = st.number_input("Bank (£m)", min_value=0.0, value=0.0, step=0.1)
            free_transfers = st.number_input("Free transfers", min_value=0, value=1)
            set_gw = st.number_input("For GW", min_value=1, value=(latest_gw or 1))

            if st.button("Save squad"):
                starter_ids = selection["starters"]
                bench_ids = selection["bench"]
                all_ids = starter_ids + bench_ids

                if len(starter_ids) != 11 or len(bench_ids) != 4:
                    st.error(f"Need 11 starters (have {len(starter_ids)}) and "
                             f"4 bench (have {len(bench_ids)}).")
                elif len(set(all_ids)) != 15:
                    st.error("Duplicate players — every player must be unique.")
                elif sum(1 for pid in bench_ids
                         if players_df.loc[players_df.player_id == pid, "pos"].iloc[0] == "GK") != 1:
                    st.error("Bench must contain exactly 1 GK.")
                else:
                    session.execute(text("DELETE FROM user_squad WHERE gw=:gw"), dict(gw=set_gw))
                    price_map = dict(zip(players_df["player_id"], players_df["price"]))
                    for pid in all_ids:
                        session.execute(text(
                            "INSERT INTO user_squad "
                            "(player_id, gw, bought_price, is_starting, is_captain) "
                            "VALUES (:pid,:gw,:price,:start,:cap)"),
                            dict(pid=int(pid), gw=set_gw, price=float(price_map[int(pid)]),
                                 start=(pid in starter_ids),
                                 cap=(pid == selection["captain"])))
                    session.execute(text(
                        "INSERT INTO team_meta (gw, bank, free_transfers) VALUES (:gw,:b,:f) "
                        "ON CONFLICT (gw) DO UPDATE SET bank=:b, free_transfers=:f"),
                        dict(gw=set_gw, b=bank, f=free_transfers))
                    session.commit()
                    st.success("Squad saved.")
                    latest_gw = set_gw

        if not latest_gw:
            st.info("No squad saved yet -- set it above.")
        else:
            squad_rows = session.execute(text("""
                SELECT p.player_id, p.web_name AS name, p.position AS pos, p.now_cost AS price,
                       COALESCE(pr.xp_mean, 0) AS xp
                FROM user_squad us JOIN players p ON p.player_id = us.player_id
                LEFT JOIN predictions pr ON pr.player_id = p.player_id AND pr.gw = us.gw
                WHERE us.gw = :gw
            """), dict(gw=latest_gw)).fetchall()
            meta = session.execute(text(
                "SELECT bank, free_transfers FROM team_meta WHERE gw=:gw"),
                dict(gw=latest_gw)).fetchone()

            if not squad_rows or not meta:
                st.warning("Squad or bank/free-transfers missing for this GW -- re-save above.")
            else:
                squad = [dict(player_id=r.player_id, name=r.name, pos=r.pos,
                              price=float(r.price), xp=float(r.xp)) for r in squad_rows]
                squad_ids = [p["player_id"] for p in squad]
                cand_rows = session.execute(text("""
                    SELECT p.player_id, p.web_name AS name, p.position AS pos,
                           p.now_cost AS price, COALESCE(pr.xp_mean, 0) AS xp
                    FROM players p
                    LEFT JOIN predictions pr ON pr.player_id = p.player_id AND pr.gw = :gw
                    WHERE p.player_id != ALL(:ids)
                """), dict(gw=latest_gw, ids=squad_ids)).fetchall()
                candidates = [dict(player_id=r.player_id, name=r.name, pos=r.pos,
                                   price=float(r.price), xp=float(r.xp)) for r in cand_rows]

                if all(p["xp"] == 0 for p in squad):
                    st.warning(f"No predictions for GW{latest_gw} yet -- run "
                               f"`python -m models.run_predictions --gw {latest_gw}` first.")

                best = best_single_transfer(squad, candidates, float(meta.bank))
                if best:
                    st.write(f"**Best single transfer:** OUT {best['out']['name']} → "
                             f"IN {best['in']['name']} (gain: {best['gain']} xP)")
                    net = evaluate_transfer_plan([best["gain"]], meta.free_transfers)
                    st.caption(f"Net after transfer-cost rules: {net} xP "
                               f"(free transfers: {meta.free_transfers})")
                else:
                    st.info("No affordable improving transfer found.")
        session.close()
    except Exception as e:
        st.error(f"Could not compute transfers: {e}")

with tab_wildcard:
    st.subheader("Wildcard optimizer (ILP)")
    budget = st.slider("Budget (£m)", 80.0, 110.0, 100.0)
    try:
        from db.connection import get_session
        from sqlalchemy import text
        from optimizers.wildcard import optimize_wildcard
        session = get_session()
        gw = st.number_input("For GW", min_value=1, value=1, key="wc_gw")
        rows = session.execute(text("""
            SELECT p.player_id, p.web_name AS name, p.position AS pos, t.short_name AS club,
                   p.now_cost AS price, COALESCE(pr.xp_mean, 0) AS xp
            FROM players p JOIN teams t ON t.team_id = p.team_id
            LEFT JOIN predictions pr ON pr.player_id = p.player_id AND pr.gw = :gw
        """), dict(gw=gw)).fetchall()
        session.close()
        pool = [dict(player_id=r.player_id, name=r.name, pos=r.pos, club=r.club,
                     price=float(r.price), xp=float(r.xp)) for r in rows]
        if not pool:
            st.warning("No players ingested yet -- run `python ops/retrain_job.py` first.")
        else:
            if all(p["xp"] == 0 for p in pool):
                st.warning(f"No predictions for GW{gw} yet -- run "
                          f"`python -m models.run_predictions --gw {gw}` first. "
                          f"Optimizing now would just pick the cheapest legal squad.")
            if st.button("Optimize wildcard squad"):
                squad = optimize_wildcard(pool, budget=budget)
                st.dataframe(pd.DataFrame(squad), use_container_width=True)
                st.caption(f"Total cost: £{sum(p['price'] for p in squad):.1f}m | "
                          f"Total xP: {sum(p['xp'] for p in squad):.2f}")
    except Exception as e:
        st.error(f"Could not run wildcard optimizer: {e}")

with tab_captain:
    st.subheader("Captaincy ranking")
    try:
        from db.connection import get_session
        from sqlalchemy import text
        from optimizers.captaincy import rank_captains
        session = get_session()
        latest_gw = session.execute(text("SELECT MAX(gw) FROM user_squad")).scalar()
        if not latest_gw:
            st.warning("No squad saved yet -- set it in the Transfers tab first.")
        else:
            rows = session.execute(text("""
                SELECT p.web_name AS name, pr.xp_mean, pr.xp_p10, pr.xp_p50, pr.xp_p90, pr.start_prob
                FROM user_squad us JOIN players p ON p.player_id = us.player_id
                JOIN predictions pr ON pr.player_id = us.player_id AND pr.gw = us.gw
                WHERE us.gw = :gw
            """), dict(gw=latest_gw)).fetchall()
            session.close()
            if not rows:
                st.warning(f"No predictions for GW{latest_gw} yet -- run "
                          f"`python -m models.run_predictions --gw {latest_gw}` first.")
            else:
                candidates = [dict(name=r.name, xp_mean=float(r.xp_mean), p10=float(r.xp_p10),
                                   p50=float(r.xp_p50), p90=float(r.xp_p90),
                                   start_prob=float(r.start_prob)) for r in rows]
                ranked = rank_captains(candidates)
                st.dataframe(pd.DataFrame(ranked), use_container_width=True)
    except Exception as e:
        st.error(f"Could not rank captains: {e}")

with tab_chips:
    st.subheader("Chip timing")
    try:
        from db.connection import get_session
        from sqlalchemy import text
        from optimizers.chip import score_bench_boost_weeks, score_triple_captain_weeks, score_free_hit_weeks
        from optimizers.dgw_bgw import flag_bgw_players
        session = get_session()

        latest_gw = session.execute(text("SELECT MAX(gw) FROM user_squad")).scalar()
        if not latest_gw:
            st.warning("No squad saved yet -- set it in the Transfers tab first.")
        else:
            squad_rows = session.execute(text(
                "SELECT us.player_id, us.is_starting, p.team_id FROM user_squad us "
                "JOIN players p ON p.player_id = us.player_id WHERE us.gw=:gw"),
                dict(gw=latest_gw)).fetchall()
            squad_ids = [r.player_id for r in squad_rows]
            bench_ids = {r.player_id for r in squad_rows if not r.is_starting}
            team_map = {r.player_id: r.team_id for r in squad_rows}

            gw_from = st.number_input("From GW", min_value=1, value=latest_gw)
            gw_to = st.number_input("To GW", min_value=gw_from, value=gw_from + 4)

            bench_xp_by_gw, captain_xp_by_gw, missing_by_gw, missing_preds = {}, {}, {}, []
            for gw in range(gw_from, gw_to + 1):
                preds = session.execute(text(
                    "SELECT player_id, xp_mean FROM predictions WHERE gw=:gw AND player_id = ANY(:ids)"),
                    dict(gw=gw, ids=squad_ids)).fetchall()
                pred_map = {r.player_id: float(r.xp_mean) for r in preds}
                if pred_map:
                    bench_xp_by_gw[gw] = sum(pred_map.get(pid, 0) for pid in bench_ids)
                    captain_xp_by_gw[gw] = max(pred_map.values(), default=0)
                else:
                    missing_preds.append(gw)

                fixture_count = {}
                for pid in squad_ids:
                    n = session.execute(text(
                        "SELECT COUNT(*) FROM fixtures WHERE gw=:gw AND (home_team_id=:t OR away_team_id=:t)"),
                        dict(gw=gw, t=team_map[pid])).scalar()
                    fixture_count[pid] = n
                squad_dicts = [{"player_id": pid} for pid in squad_ids]
                missing_by_gw[gw] = len(flag_bgw_players(squad_dicts, fixture_count))
            session.close()

            if missing_preds:
                st.warning(f"No predictions for GW{missing_preds} yet -- run "
                          f"`python -m models.run_predictions --gw N` for those, then refresh. "
                          f"Bench Boost / Triple Captain below only cover GWs with predictions; "
                          f"Free Hit blank-count uses real fixtures and doesn't need predictions.")

            if bench_xp_by_gw:
                st.write("**Bench Boost candidate weeks** (highest combined bench xP):")
                st.table(score_bench_boost_weeks(bench_xp_by_gw))
                st.write("**Triple Captain candidate weeks** (highest single-player ceiling):")
                st.table(score_triple_captain_weeks(captain_xp_by_gw))
            st.write("**Free Hit candidate weeks** (most squad players blanking, from real fixtures):")
            st.table(score_free_hit_weeks(missing_by_gw))
    except Exception as e:
        st.error(f"Could not compute chip timing: {e}")

with tab_track:
    st.subheader("Recommendation tracking")
    try:
        from db.connection import get_session
        from sqlalchemy import text
        session = get_session()
        rows = session.execute(text("""
            SELECT rec_id, gw, rec_type, payload, created_at, actual_outcome, evaluated_at
            FROM recommendations ORDER BY created_at DESC
        """)).fetchall()
        session.close()

        if not rows:
            st.warning("No recommendations logged yet. tracking.log_recommendation() "
                       "needs to be called by the optimizers/agent when they make a call.")
        else:
            df = pd.DataFrame(rows, columns=["rec_id", "gw", "rec_type", "payload",
                                              "created_at", "actual_outcome", "evaluated_at"])
            df["status"] = df["evaluated_at"].apply(lambda x: "Evaluated" if pd.notna(x) else "Pending")

            c1, c2 = st.columns(2)
            c1.metric("Total recommendations", len(df))
            c2.metric("Evaluated", int((df["status"] == "Evaluated").sum()))

            st.caption("By type:")
            st.dataframe(df.groupby(["rec_type", "status"]).size().unstack(fill_value=0),
                         use_container_width=True)

            st.caption("Most recent evaluated recommendations (raw payload vs actual outcome -- "
                       "wire a real accuracy metric here once payload/actual_outcome's key "
                       "schema from your optimizers is known):")
            evaluated = df[df["status"] == "Evaluated"][["gw", "rec_type", "payload", "actual_outcome", "evaluated_at"]]
            st.dataframe(evaluated.head(20), use_container_width=True)
    except Exception as e:
        st.error(f"Could not query database: {e}")

with tab_ask:
    st.subheader("Ask the agent")
    try:
        from db.connection import get_session
        from sqlalchemy import text
        session = get_session()
        recs = session.execute(text(
            "SELECT rec_id, gw, rec_type, payload, created_at FROM recommendations "
            "ORDER BY created_at DESC LIMIT 50"
        )).fetchall()
        session.close()

        if not recs:
            st.warning("No recommendations logged yet -- nothing for the agent to explain. "
                       "Recommendations get logged once the optimizer tabs actually run and "
                       "call tracking.log_recommendation().")
        else:
            options = {f"#{r.rec_id} \u2022 {r.rec_type} \u2022 GW{r.gw} \u2022 {r.created_at}": r for r in recs}
            choice = st.selectbox("Pick a logged recommendation to ask about:", list(options.keys()))
            q = st.text_input("Your question (optional -- leave blank for a plain-language explanation):")
            if st.button("Ask"):
                rec = options[choice]
                try:
                    from agent.llm_agent import explain_recommendation
                    with st.spinner("Asking the agent..."):
                        answer = explain_recommendation(rec.rec_type, rec.payload, q)
                    st.write(answer)
                except RuntimeError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"Agent call failed: {e}")
    except Exception as e:
        st.error(f"Could not query database: {e}")