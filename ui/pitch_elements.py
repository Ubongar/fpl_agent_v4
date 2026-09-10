"""Drag-and-drop FPL pitch built with streamlit-elements (Material UI + react-grid-layout)."""
import streamlit as st
from streamlit_elements import elements, dashboard, mui, sync, lazy

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

PITCH_BG = {
    "background": "linear-gradient(180deg,#2f7d32 0%,#3a9a3f 50%,#2f7d32 100%)",
    "borderRadius": "14px",
    "padding": "12px",
    "border": "2px solid #1f5a22",
}

CARD_SX = {
    "display": "flex",
    "flexDirection": "column",
    "justifyContent": "center",
    "alignItems": "center",
    "height": "100%",
    "bgcolor": "background.paper",
    "borderRadius": 2,
    "boxShadow": 2,
    "cursor": "grab",
    "userSelect": "none",
    "p": 1,
    "textAlign": "center",
    "&:hover": {"boxShadow": 6},
}

def _fmt(r):
    return f"{r['name']} · {r['club']} · £{r['price']:.1f}m"


def _slot_layout(formation, prefix):
    """Return a react-grid-layout list for starters on a 12-col grid."""
    def_pos, mid_pos, fwd_pos = FORMATIONS[formation]
    items = []

    # GK row (y=0)
    items.append(dashboard.Item(f"{prefix}_gk_0", 5, 0, 2, 1))

    # DEF row (y=1)
    def_start = (12 - def_pos * 2) // 2
    for i in range(def_pos):
        items.append(dashboard.Item(f"{prefix}_def_{i}", def_start + i * 2, 1, 2, 1))

    # MID row (y=2)
    mid_start = (12 - mid_pos * 2) // 2
    for i in range(mid_pos):
        items.append(dashboard.Item(f"{prefix}_mid_{i}", mid_start + i * 2, 2, 2, 1))

    # FWD row (y=3)
    fwd_start = (12 - fwd_pos * 2) // 2
    for i in range(fwd_pos):
        items.append(dashboard.Item(f"{prefix}_fwd_{i}", fwd_start + i * 2, 3, 2, 1))

    return items


def render_squad_builder_elements(players, key_prefix="sb_el"):
    """players: DataFrame(player_id, name, pos, club, price)."""
    st.markdown("### Formation")
    formation = st.selectbox(
        "Formation", list(FORMATIONS.keys()),
        index=list(FORMATIONS).index("4-4-2"), key=f"{key_prefix}_formation",
        label_visibility="collapsed",
    )

    # ----- session state bootstrap -----
    state_key = f"{key_prefix}_assignments"
    if state_key not in st.session_state:
        st.session_state[state_key] = {}  # slot_id -> player_id

    pool_key = f"{key_prefix}_pool"
    if pool_key not in st.session_state:
        st.session_state[pool_key] = list(players["player_id"].astype(int))

    cap_key = f"{key_prefix}_cap"
    vice_key = f"{key_prefix}_vice"
    if cap_key not in st.session_state:
        st.session_state[cap_key] = None
    if vice_key not in st.session_state:
        st.session_state[vice_key] = None

    pid_to_row = {int(r["player_id"]): r for _, r in players.iterrows()}

    def handle_drop(slot_id, event):
        """Fired when a card is dragged onto a new grid position."""
        # react-grid-layout gives us the new x/y; we just remember the mapping.
        # For this UI we rely on the card's own onDragEnd to store the slot.
        pass

    def on_card_drag_end(slot_id):
        """Store that this slot now holds this player (visual move only)."""
        # The actual player assignment happens when user picks from dropdown
        # inside the card; drag-and-drop here is purely visual layout.
        pass

    # ----- pitch -----
    layout = _slot_layout(formation, key_prefix)

    with elements(f"{key_prefix}_frame"):
        with dashboard.Grid(
            layout,
            draggableHandle=".draggable",
            rowHeight=90,
            isDraggable=True,
            isResizable=False,
        ):
            # GK
            with mui.Card(key=f"{key_prefix}_gk_0", sx=CARD_SX):
                mui.CardHeader(title="GK", className="draggable",
                               sx={"pb": 0, "textAlign": "center", "width": "100%"})
                with mui.CardContent(sx={"p": 1, "width": "100%"}):
                    _player_select(
                        players[players["pos"] == "GK"],
                        f"{key_prefix}_gk_0",
                        state_key, pid_to_row, key_prefix,
                    )

            # DEF / MID / FWD
            for pos, count in [("DEF", FORMATIONS[formation][0]),
                               ("MID", FORMATIONS[formation][1]),
                               ("FWD", FORMATIONS[formation][2])]:
                for i in range(count):
                    slot = f"{key_prefix}_{pos.lower()}_{i}"
                    with mui.Card(key=slot, sx=CARD_SX):
                        mui.CardHeader(title=pos, className="draggable",
                                       sx={"pb": 0, "textAlign": "center", "width": "100%"})
                        with mui.CardContent(sx={"p": 1, "width": "100%"}):
                            _player_select(
                                players[players["pos"] == pos],
                                slot, state_key, pid_to_row, key_prefix,
                            )

    # ----- bench -----
    st.markdown("### Bench")
    bench_cols = st.columns(4)
    bench_ids = []
    bench_slots = []
    for i, pos in enumerate(["GK", "DEF", "MID", "FWD"]):
        slot = f"{key_prefix}_bench_{i}"
        bench_slots.append(slot)
        with bench_cols[i]:
            pid = _player_select_simple(
                players[players["pos"] == pos], slot,
                state_key, pid_to_row, key_prefix,
            )
            if pid:
                bench_ids.append(pid)

    # ----- captain / vice -----
    starter_ids = [
        st.session_state[state_key].get(s)
        for s in [it["i"] for it in layout]
    ]
    starter_ids = [p for p in starter_ids if p]

    id_to_name = {int(r["player_id"]): r["name"] for _, r in players.iterrows()}

    c1, c2 = st.columns(2)
    cap_choice = c1.selectbox(
        "Captain (C)",
        [""] + [id_to_name[p] for p in starter_ids],
        key=f"{key_prefix}_cap_sel",
    )
    vice_choice = c2.selectbox(
        "Vice (V)",
        [""] + [id_to_name[p] for p in starter_ids if id_to_name[p] != cap_choice],
        key=f"{key_prefix}_vice_sel",
    )

    name_to_id = {v: k for k, v in id_to_name.items()}

    total = sum(float(pid_to_row[p]["price"]) for p in starter_ids + bench_ids if p in pid_to_row)

    st.caption(
        f"{len(starter_ids)} starters + {len(bench_ids)} bench · £{total:.1f}m"
    )

    return {
        "formation": formation,
        "starters": starter_ids,
        "bench": bench_ids,
        "captain": name_to_id.get(cap_choice),
        "vice": name_to_id.get(vice_choice),
    }


def _player_select(pos_df, slot, state_key, pid_to_row, key_prefix):
    """Dropdown inside a pitch card that writes to session state."""
    options = [""] + [
        f"{r['name']} · £{r['price']:.1f}m"
        for _, r in pos_df.sort_values("price", ascending=False).iterrows()
    ]
    label_to_id = {"" : None}
    for _, r in pos_df.iterrows():
        label_to_id[f"{r['name']} · £{r['price']:.1f}m"] = int(r["player_id"])

    current = st.session_state[state_key].get(slot)
    current_label = ""
    if current and current in pid_to_row:
        r = pid_to_row[current]
        current_label = f"{r['name']} · £{r['price']:.1f}m"

    idx = options.index(current_label) if current_label in options else 0

    choice = mui.Select(
        value=options[idx],
        onChange=sync(f"{key_prefix}_sel_{slot}"),
        sx={"width": "100%", "fontSize": "0.75rem"},
        displayEmpty=True,
        renderValue=lambda v: v if v else "— pick —",
    )
    # menu items are added as children (mui.MenuItem)
    with choice:
        for opt in options:
            mui.MenuItem(opt if opt else "—", value=opt)

    # read back from session state after rerun
    sel_state = f"{key_prefix}_sel_{slot}"
    if sel_state in st.session_state and st.session_state[sel_state] is not None:
        val = st.session_state[sel_state].target.value
        st.session_state[state_key][slot] = label_to_id.get(val)

    return st.session_state[state_key].get(slot)


def _player_select_simple(pos_df, slot, state_key, pid_to_row, key_prefix):
    """Plain Streamlit selectbox for the bench (simpler, no MUI needed)."""
    options = [""] + [
        f"{r['name']} · £{r['price']:.1f}m"
        for _, r in pos_df.sort_values("price", ascending=False).iterrows()
    ]
    label_to_id = {"" : None}
    for _, r in pos_df.iterrows():
        label_to_id[f"{r['name']} · £{r['price']:.1f}m"] = int(r["player_id"])

    current = st.session_state[state_key].get(slot)
    current_label = ""
    if current and current in pid_to_row:
        r = pid_to_row[current]
        current_label = f"{r['name']} · £{r['price']:.1f}m"

    idx = options.index(current_label) if current_label in options else 0
    choice = st.selectbox(slot, options, index=idx, key=f"{key_prefix}_bench_sel_{slot}")
    pid = label_to_id[choice]
    st.session_state[state_key][slot] = pid
    return pid