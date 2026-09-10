"""FPL-style pitch squad builder — dropdown version (position-locked, state-safe)."""
import streamlit as st
import pandas as pd

FORMATIONS = {
    "3-4-3": (3, 4, 3),
    "3-5-2": (3, 5, 2),
    "4-3-3": (4, 3, 3),
    "4-4-2": (4, 4, 2),
    "4-5-1": (4, 5, 1),
    "5-2-3": (5, 2, 3),
    "5-3-2": (5, 3, 2),
    "5-4-1": (5, 4, 1),
}

VALID_POSITIONS = ["GK", "DEF", "MID", "FWD"]

POSITION_ALIASES = {
    "GK": "GK", "GKP": "GK", "GOALKEEPER": "GK", "KEEPER": "GK",
    "DEF": "DEF", "DEFENDER": "DEF", "D": "DEF",
    "MID": "MID", "MIDFIELDER": "MID", "M": "MID",
    "FWD": "FWD", "FORWARD": "FWD", "STRIKER": "FWD", "ATTACKER": "FWD", "F": "FWD",
}

PITCH_CSS = """
<style>
.pitch-strip {
    background: linear-gradient(180deg,#2f7d32 0%,#3a9a3f 100%);
    color: #fff; padding: 4px 12px; border-radius: 8px;
    font-weight: 600; font-size: 0.8rem; letter-spacing: 1px;
    text-transform: uppercase; margin: 10px 0 4px 0; text-align: center;
}
.bench-strip {
    background: linear-gradient(180deg,#7a5c1e 0%,#a3801e 100%);
    color: #fff; padding: 4px 12px; border-radius: 8px;
    font-weight: 600; font-size: 0.8rem; letter-spacing: 1px;
    text-transform: uppercase; margin: 16px 0 4px 0; text-align: center;
}
.slot-tag {
    display: inline-block; background: #1f5a22; color: #fff;
    font-size: 0.65rem; font-weight: 700; letter-spacing: 1px;
    padding: 2px 8px; border-radius: 4px; margin-bottom: 2px;
}
.slot-tag-flex {
    display: inline-block; background: #8a6d1e; color: #fff;
    font-size: 0.65rem; font-weight: 700; letter-spacing: 1px;
    padding: 2px 8px; border-radius: 4px; margin-bottom: 2px;
}
</style>
"""


def _normalize_position(raw):
    if raw is None:
        return ""
    return POSITION_ALIASES.get(str(raw).strip().upper(), "")


def _label(row):
    """'Salah · MID · LIV · £13.0m'"""
    return f"{row['name']} · {row['pos']} · {row['club']} · £{row['price']:.1f}m"


def _render_slot_from_pool(pool, slot_key, display_label, picks, key_prefix, flex=False):
    """One dropdown locked to `pool`. Widget keeps its own state; we only
    reset it when it holds a value that's no longer a legal option."""
    widget_key = f"{key_prefix}_sel_{slot_key}"

    # 1. Build the legal option list: this slot's pool, minus players taken elsewhere.
    taken = {v for k, v in picks.items() if k != slot_key and v is not None}
    avail = pool[~pool["player_id"].isin(taken)]
    options = [""] + [_label(r) for _, r in avail.iterrows()]

    # 2. If picks already has a value for this slot, guarantee its label is an option.
    current_id = picks.get(slot_key)
    if current_id is not None:
        match = pool[pool["player_id"] == current_id]
        if not match.empty:
            current_label = _label(match.iloc[0])
            if current_label not in options:
                options.append(current_label)

    # 3. Clear stale widget state ONLY IF its stored value isn't a legal option
    #    (this is what kills ghosts, without fighting the user's live click).
    if widget_key in st.session_state and st.session_state[widget_key] not in options:
        st.session_state[widget_key] = ""

    # 4. Render. From here the widget owns its value.
    tag_cls = "slot-tag-flex" if flex else "slot-tag"
    st.markdown(f'<span class="{tag_cls}">{display_label}</span>', unsafe_allow_html=True)

    choice = st.selectbox(
        display_label, options,
        key=widget_key,
        label_visibility="collapsed",
    )

    # 5. Sync picks FROM the widget (the correct direction).
    chosen_id = None
    if choice:
        for _, r in pool.iterrows():
            if _label(r) == choice:
                chosen_id = int(r["player_id"])
                break
    picks[slot_key] = chosen_id
    return chosen_id


def render_squad_builder(players: pd.DataFrame, key_prefix: str = "sb", debug: bool = True):
    """players: DataFrame with columns player_id, name, pos, club, price."""
    st.markdown(PITCH_CSS, unsafe_allow_html=True)

    players = players.copy()
    players["pos"] = players["pos"].apply(_normalize_position)
    unknown = players[players["pos"] == ""]
    if not unknown.empty:
        st.warning(f"{len(unknown)} players have unrecognized positions and will be hidden.")

    players = players[players["pos"].isin(VALID_POSITIONS)]
    players["player_id"] = players["player_id"].astype(int)

    # ---------------- Formation + Reset ----------------
    col_f, col_r = st.columns([4, 1])
    with col_f:
        formation = st.selectbox(
            "Formation", list(FORMATIONS.keys()),
            index=list(FORMATIONS).index("4-4-2"),
            key=f"{key_prefix}_formation",
        )
    with col_r:
        st.write("")  # vertical spacer
        if st.button("🗑 Reset picks", key=f"{key_prefix}_reset"):
            st.session_state[f"{key_prefix}_picks"] = {}
            for k in list(st.session_state.keys()):
                if k.startswith(f"{key_prefix}_sel_"):
                    del st.session_state[k]
            st.rerun()

    def_n, mid_n, fwd_n = FORMATIONS[formation]

    picks_key = f"{key_prefix}_picks"
    if picks_key not in st.session_state:
        st.session_state[picks_key] = {}
    picks = st.session_state[picks_key]

    by_pos = {p: players[players["pos"] == p].reset_index(drop=True)
              for p in VALID_POSITIONS}

    outfield = players[players["pos"].isin(["DEF", "MID", "FWD"])].copy()
    outfield["_pos_order"] = outfield["pos"].map({"DEF": 0, "MID": 1, "FWD": 2})
    outfield = outfield.sort_values(["_pos_order", "price"], ascending=[True, False]).reset_index(drop=True)

    # ---------------- Debug panel ----------------
    if debug:
        with st.expander("🔍 Debug — pools, picks, and exclusions", expanded=False):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("GK pool", len(by_pos["GK"]))
            c2.metric("DEF pool", len(by_pos["DEF"]))
            c3.metric("MID pool", len(by_pos["MID"]))
            c4.metric("FWD pool", len(by_pos["FWD"]))

            st.write("**Current picks** (`slot → player`):")
            if not picks or all(v is None for v in picks.values()):
                st.caption("No players assigned.")
            else:
                id_to_name_dbg = {int(r["player_id"]): f"{r['name']} ({r['pos']})"
                                  for _, r in players.iterrows()}
                rows = [{"slot": k, "player_id": v, "player": id_to_name_dbg.get(v, "?")}
                        for k, v in picks.items() if v is not None]
                st.dataframe(pd.DataFrame(rows), use_container_width=True)

            st.write("**Every GK in the pool** (this is what a Bench GK dropdown can show):")
            gk_view = by_pos["GK"][["player_id", "name", "club", "price"]].copy()
            taken_ids = {v for v in picks.values() if v is not None}
            gk_view["taken_elsewhere"] = gk_view["player_id"].isin(taken_ids)
            st.dataframe(gk_view, use_container_width=True)

            st.caption("If a GK you expect isn't in this table, they're not in `players_df`. "
                       "If they're here with `taken_elsewhere=True`, they're already in another slot.")

    # ---------------- Starters ----------------
    st.markdown('<div class="pitch-strip">🧤 Goalkeeper</div>', unsafe_allow_html=True)
    gk_cols = st.columns([2, 1, 2])
    with gk_cols[1]:
        _render_slot_from_pool(by_pos["GK"], "gk_0", "GK", picks, key_prefix)

    st.markdown('<div class="pitch-strip">🛡️ Defenders</div>', unsafe_allow_html=True)
    for i, c in enumerate(st.columns(def_n)):
        with c:
            _render_slot_from_pool(by_pos["DEF"], f"def_{i}", f"DEF {i+1}", picks, key_prefix)

    st.markdown('<div class="pitch-strip">🎯 Midfielders</div>', unsafe_allow_html=True)
    for i, c in enumerate(st.columns(mid_n)):
        with c:
            _render_slot_from_pool(by_pos["MID"], f"mid_{i}", f"MID {i+1}", picks, key_prefix)

    st.markdown('<div class="pitch-strip">⚡ Forwards</div>', unsafe_allow_html=True)
    for i, c in enumerate(st.columns(fwd_n)):
        with c:
            _render_slot_from_pool(by_pos["FWD"], f"fwd_{i}", f"FWD {i+1}", picks, key_prefix)

    # ---------------- Bench: 1 GK + 3 outfield ----------------
    st.markdown('<div class="bench-strip">🪑 Bench — 1 GK + 3 outfield (any mix)</div>',
                unsafe_allow_html=True)
    bench_cols = st.columns(4)
    bench_ids = []

    with bench_cols[0]:
        pid = _render_slot_from_pool(by_pos["GK"], "bench_gk", "Bench GK", picks, key_prefix)
        if pid:
            bench_ids.append(pid)

    for i in range(3):
        with bench_cols[i + 1]:
            pid = _render_slot_from_pool(
                outfield, f"bench_of_{i}", f"Bench {i+1}", picks, key_prefix, flex=True,
            )
            if pid:
                bench_ids.append(pid)

    # ---------------- Starters summary ----------------
    starter_ids = [picks.get("gk_0")]
    starter_ids += [picks.get(f"def_{i}") for i in range(def_n)]
    starter_ids += [picks.get(f"mid_{i}") for i in range(mid_n)]
    starter_ids += [picks.get(f"fwd_{i}") for i in range(fwd_n)]
    starter_ids = [p for p in starter_ids if p is not None]

    # ---------------- Captain / Vice ----------------
    id_to_name = {int(r["player_id"]): r["name"] for _, r in players.iterrows()}
    id_to_pos = {int(r["player_id"]): r["pos"] for _, r in players.iterrows()}
    starter_names = [id_to_name[p] for p in starter_ids]

    st.markdown("---")
    c1, c2 = st.columns(2)
    cap = c1.selectbox("Captain (C)", [""] + starter_names, key=f"{key_prefix}_cap")
    vice = c2.selectbox(
        "Vice (V)", [""] + [n for n in starter_names if n != cap],
        key=f"{key_prefix}_vice",
    )
    name_to_id = {v: k for k, v in id_to_name.items()}

    # ---------------- Summary ----------------
    price_map = dict(zip(players["player_id"], players["price"]))
    total = sum(price_map.get(p, 0.0) for p in starter_ids + bench_ids)

    bench_pos_counts = {}
    for pid in bench_ids:
        pos = id_to_pos.get(pid, "?")
        bench_pos_counts[pos] = bench_pos_counts.get(pos, 0) + 1

    bench_str = " · ".join(f"{n} {p}" for p, n in sorted(bench_pos_counts.items()))
    ready = len(starter_ids) == 11 and len(bench_ids) == 4
    icon = "✅" if ready else "⚠️"

    st.caption(
        f"{icon} {len(starter_ids)}/11 starters · {len(bench_ids)}/4 bench "
        f"({bench_str or 'empty'}) · £{total:.1f}m · {formation}"
    )

    return {
        "formation": formation,
        "starters": starter_ids,
        "bench": bench_ids,
        "captain": name_to_id.get(cap),
        "vice": name_to_id.get(vice),
    }