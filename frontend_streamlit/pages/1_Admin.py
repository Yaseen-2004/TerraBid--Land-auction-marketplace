from __future__ import annotations

from datetime import datetime, timedelta

import streamlit as st

from lib import api, auth
from lib.api import ApiError
from lib.format import format_datetime, format_inr, format_time
from lib.property_form import open_create_dialog, open_edit_dialog
from lib.theme import status_badge_html

st.set_page_config(page_title="TerraBid Admin", page_icon="\U0001f6e0️", layout="wide")
auth.init_session()

if not auth.require_role("ADMIN"):
    st.stop()

st.title("Admin dashboard")
st.caption("Manage parcels, auctions and users.")

top1, top2 = st.columns([5, 1])
if top2.button("+ Create property", type="primary", use_container_width=True):
    open_create_dialog()

tab_dashboard, tab_properties, tab_auctions, tab_users = st.tabs(["Dashboard", "Properties", "Auctions", "Users"])

# ---------------------------------------------------------------------------- dashboard

with tab_dashboard:
    try:
        stats = api.admin_stats()
    except ApiError as exc:
        st.error(exc.message)
        stats = None
    if stats:
        rows = [
            ("Total properties", stats["total_properties"]),
            ("Active auctions", stats["active_auctions"]),
            ("Upcoming auctions", stats["upcoming_auctions"]),
            ("Completed auctions", stats["completed_auctions"]),
            ("Cancelled auctions", stats["cancelled_auctions"]),
            ("Registered users", stats["registered_users"]),
            ("Total bids", stats["total_bids"]),
            ("Rejected bids", stats["rejected_bids"]),
            ("Total sales value", format_inr(stats["total_sales_value"])),
        ]
        cols = st.columns(3)
        for i, (label, value) in enumerate(rows):
            cols[i % 3].metric(label, value, border=True)

# ---------------------------------------------------------------------------- properties

with tab_properties:
    try:
        properties = api.list_properties(limit=500, status=["AVAILABLE", "IN_AUCTION", "SOLD", "UNSOLD", "WITHDRAWN"])
    except ApiError as exc:
        st.error(exc.message)
        properties = []

    if not properties:
        st.caption("No properties yet.")
    for prop in properties:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 2, 2, 3])
            c1.markdown(f"**{prop['title']}**  \n`#{prop['id']}` · {prop['location']}")
            area_text = f"{prop['area']:,.0f} sq.ft" if prop.get("area") else "—"
            c2.write(area_text)
            c3.write(format_inr(prop["base_price"]))
            auction = prop.get("auction")
            c4.markdown(status_badge_html(auction["status"] if auction else "NONE"), unsafe_allow_html=True)

            actions = st.columns(4)
            if actions[0].button("Edit", key=f"edit_{prop['id']}", use_container_width=True):
                open_edit_dialog(prop)
            can_schedule = (not auction or auction["status"] in ("ENDED", "CANCELLED")) and prop["status"] not in ("SOLD", "WITHDRAWN")
            if can_schedule and actions[1].button("Schedule auction", key=f"sched_{prop['id']}", use_container_width=True):
                st.session_state["_admin_schedule_property"] = prop
            confirm_key = f"confirm_delete_{prop['id']}"
            if not st.session_state.get(confirm_key):
                if actions[3].button("Delete", key=f"del_{prop['id']}", use_container_width=True):
                    st.session_state[confirm_key] = True
                    st.rerun()
            else:
                if actions[3].button("Confirm delete?", key=f"del_confirm_{prop['id']}", type="primary", use_container_width=True):
                    try:
                        api.delete_property(prop["id"])
                        st.toast("Property deleted.", icon="\U0001f5d1️")
                    except ApiError as exc:
                        st.error(exc.message)
                    st.session_state.pop(confirm_key, None)
                    st.rerun()

    if st.session_state.get("_admin_schedule_property"):
        target = st.session_state["_admin_schedule_property"]
        with st.form(f"schedule_{target['id']}"):
            st.markdown(f"**Schedule auction — {target['title']}**")
            c1, c2 = st.columns(2)
            now = datetime.now()
            start_date = c1.date_input("Start date", value=now.date())
            start_time = c1.time_input("Start time", value=(now + timedelta(minutes=5)).time().replace(microsecond=0))
            end_date = c2.date_input("End date", value=now.date())
            end_time = c2.time_input("End time", value=(now + timedelta(hours=1)).time().replace(microsecond=0))
            starting_price = st.number_input("Starting price (₹)", min_value=0.0, value=float(target["base_price"]), step=10000.0)
            increment = st.number_input("Minimum increment (₹)", min_value=1.0, value=50000.0, step=5000.0)
            submitted = st.form_submit_button("Schedule", type="primary")
        if submitted:
            start_dt = datetime.combine(start_date, start_time).astimezone()
            end_dt = datetime.combine(end_date, end_time).astimezone()
            try:
                api.create_auction(
                    {
                        "property_id": target["id"],
                        "start_time": start_dt.isoformat(),
                        "end_time": end_dt.isoformat(),
                        "starting_price": starting_price,
                        "minimum_increment": increment,
                    }
                )
                st.toast("Auction scheduled.", icon="✅")
            except ApiError as exc:
                st.error(exc.message)
            st.session_state.pop("_admin_schedule_property", None)
            st.rerun()
        if st.button("Cancel scheduling"):
            st.session_state.pop("_admin_schedule_property", None)
            st.rerun()

# ---------------------------------------------------------------------------- auctions

with tab_auctions:
    try:
        auctions = api.list_auctions(limit=500)
    except ApiError as exc:
        st.error(exc.message)
        auctions = []

    if not auctions:
        st.caption("No auctions yet.")
    for a in auctions:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 2, 2, 3])
            prop = a.get("property") or {}
            c1.markdown(f"**{prop.get('title', '?')}**  \nAuction `#{a['id']}` · {prop.get('location', '')}")
            c2.markdown(status_badge_html(a["status"]), unsafe_allow_html=True)
            c3.write(f"{format_inr(a['current_price'])} · {a['bid_count']} bids")
            winner = a.get("winner_name") or (a.get("highest_bidder") and f"{a['highest_bidder']} (leading)") or "—"
            c4.write(winner)

            actions = st.columns(4)
            if actions[0].button("View bids", key=f"bids_{a['id']}", use_container_width=True):
                st.session_state["_admin_view_auction"] = a["id"]
            if a["status"] == "UPCOMING" and actions[1].button("Start", key=f"start_{a['id']}", use_container_width=True):
                try:
                    api.start_auction(a["id"])
                    st.toast("Auction started.", icon="▶️")
                except ApiError as exc:
                    st.error(exc.message)
                st.rerun()
            if a["status"] == "LIVE" and actions[1].button("End now", key=f"end_{a['id']}", use_container_width=True):
                try:
                    api.end_auction(a["id"])
                    st.toast("Auction ended.", icon="\U0001f3c1")
                except ApiError as exc:
                    st.error(exc.message)
                st.rerun()
            if a["status"] in ("UPCOMING", "LIVE") and actions[2].button("Cancel", key=f"cancel_{a['id']}", use_container_width=True):
                try:
                    api.cancel_auction(a["id"])
                    st.toast("Auction cancelled.", icon="⛔")
                except ApiError as exc:
                    st.error(exc.message)
                st.rerun()

    if st.session_state.get("_admin_view_auction"):
        auction_id = st.session_state["_admin_view_auction"]
        with st.container(border=True):
            st.markdown(f"**Bids for auction #{auction_id}**")
            try:
                bidders = api.auction_bidders(auction_id)
                history = api.list_bids(auction_id, include_rejected=True, limit=200)
            except ApiError as exc:
                st.error(exc.message)
                bidders, history = [], []

            bc, hc = st.columns(2)
            with bc:
                st.markdown("_Bidders_")
                if bidders:
                    st.dataframe(
                        [{"Name": b["name"], "Email": b["email"], "Bids": b["bid_count"], "Highest": format_inr(b["highest_amount"])} for b in bidders],
                        hide_index=True,
                        use_container_width=True,
                    )
                else:
                    st.caption("No bidders yet.")
            with hc:
                st.markdown("_Full bid history (incl. rejected)_")
                if history:
                    st.dataframe(
                        [
                            {
                                "Amount": format_inr(b["amount"]),
                                "Bidder": b["bidder_name"],
                                "Time": format_time(b["bid_time"]),
                                "Result": b.get("rejection_reason") or b["status"],
                            }
                            for b in history
                        ],
                        hide_index=True,
                        use_container_width=True,
                    )
                else:
                    st.caption("No bids yet.")
            if st.button("Close"):
                st.session_state.pop("_admin_view_auction", None)
                st.rerun()

# ---------------------------------------------------------------------------- users

with tab_users:
    try:
        users = api.admin_users()
    except ApiError as exc:
        st.error(exc.message)
        users = []

    def _change_role(user_id: int, key: str, previous: str) -> None:
        try:
            api.update_user(user_id, {"role": st.session_state[key]})
            st.toast("Role updated.", icon="✅")
        except ApiError as exc:
            st.session_state[key] = previous  # revert so the widget matches the server
            st.session_state["_admin_user_error"] = exc.message

    if st.session_state.get("_admin_user_error"):
        st.error(st.session_state.pop("_admin_user_error"))

    roles = ["BIDDER", "SELLER", "ADMIN"]
    current_user_id = auth.current_user()["id"]
    for u in users:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
            c1.markdown(f"**{u['name']}**  \n{u['email']}")
            c2.write(format_datetime(u["created_at"]))
            is_self = u["id"] == current_user_id
            role_key = f"role_{u['id']}"
            # Re-sync with the server each render so the widget never drifts from reality.
            st.session_state[role_key] = u["role"]
            c3.selectbox(
                "Role", roles, key=role_key, disabled=is_self, label_visibility="collapsed",
                on_change=_change_role, args=(u["id"], role_key, u["role"]),
            )
            toggle_label = "Active" if u["is_active"] else "Disabled"
            if c4.button(toggle_label, key=f"active_{u['id']}", disabled=is_self, use_container_width=True):
                try:
                    api.update_user(u["id"], {"is_active": not u["is_active"]})
                    st.toast("User updated.", icon="✅")
                except ApiError as exc:
                    st.error(exc.message)
                st.rerun()
