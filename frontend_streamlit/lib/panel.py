"""The auction side panel: property facts, current price, bid form, live history.

Streamlit has no browser push like the original app's WebSocket — st.fragment's
run_every re-executes just this panel on a timer, polling the backend. That
means updates land every POLL_SECONDS rather than instantly, and the countdown
ticks in POLL_SECONDS steps rather than every second. The backend itself is
unchanged and still enforces everything atomically; this is a UI-refresh
trade-off only.
"""

from __future__ import annotations

import streamlit as st

from lib import api, auth
from lib.api import ApiError
from lib.format import (
    format_area_compact,
    format_compact_inr,
    format_datetime,
    format_duration,
    format_inr,
    format_time,
    seconds_until,
)
from lib.theme import status_badge_html

POLL_SECONDS = 3


def _quick_bid_amounts(min_next_bid: float, increment: float) -> list[float]:
    return [min_next_bid + increment * (n - 1) for n in (1, 2, 5)]


def _set_bid_amount(key: str, value: float) -> None:
    st.session_state[key] = value


@st.fragment(run_every=POLL_SECONDS)
def render_auction_panel() -> None:
    property_id = st.session_state.get("selected_property_id")
    if not property_id:
        st.info("Click a parcel on the map, or use search, to view its auction.")
        return

    try:
        prop = api.get_property(property_id)
    except ApiError as exc:
        st.error(f"Could not load this property: {exc.message}")
        return

    header_col, close_col = st.columns([6, 1])
    with header_col:
        st.subheader(prop["title"])
        st.caption(f"\U0001f4cd {prop['location']} · #{prop['id']}")
    with close_col:
        if st.button("✕", key="close_panel", help="Close", use_container_width=True):
            st.session_state["selected_property_id"] = None
            st.rerun()

    if prop.get("image_url"):
        st.image(prop["image_url"], use_container_width=True)

    # Compact currency notation (e.g. ₹30L) here since this narrow two-up row truncates
    # full-precision amounts; the current bid below has the full width for full precision.
    fc1, fc2 = st.columns(2)
    fc1.metric("Area", format_area_compact(prop["area"]))
    fc2.metric("Base price", format_compact_inr(prop["base_price"]))
    if prop.get("description"):
        st.caption(prop["description"])

    auction = prop.get("auction")
    if not auction:
        st.warning("No auction is scheduled for this property yet.")
        return

    status = auction["status"]
    st.markdown(status_badge_html(status), unsafe_allow_html=True)

    label = "Final price" if status == "ENDED" else ("Current bid" if auction["bid_count"] else "Starting price")
    st.metric(label, format_inr(auction["current_price"]), border=True)

    m1, m2 = st.columns(2)
    winner_or_leader = "Winner" if status == "ENDED" else "Highest bidder"
    holder = auction.get("winner_name") if status == "ENDED" else auction.get("highest_bidder")
    m1.metric(winner_or_leader, holder or "—")
    if status in ("LIVE", "UPCOMING"):
        m2.metric("Minimum next bid", format_inr(auction["min_next_bid"]))
    else:
        m2.metric("Bids placed", auction["bid_count"])

    if status == "UPCOMING":
        st.info(f"⏳ Starts in **{format_duration(seconds_until(auction['start_time']))}** — opens {format_datetime(auction['start_time'])}")
    elif status == "LIVE":
        remaining = seconds_until(auction["end_time"])
        urgency = "\U0001f534" if remaining < 60 else "⏳"
        st.info(f"{urgency} Auction ends in **{format_duration(remaining)}** (updates every {POLL_SECONDS}s)")
    elif status == "CANCELLED":
        st.error("This auction was cancelled.")
    elif status == "ENDED":
        if auction.get("winner_name"):
            st.success(f"\U0001f3c6 Sold to **{auction['winner_name']}** for {format_inr(auction['current_price'])}")
        else:
            st.info("Auction ended with no bids.")

    user = auth.current_user()
    if status == "LIVE":
        auction_id = auction["id"]
        amount_key = f"bid_amount_{auction_id}"
        min_next = float(auction["min_next_bid"])
        increment = float(auction["minimum_increment"])
        st.session_state.setdefault(amount_key, min_next)

        if not user:
            st.info("Log in from the sidebar to place a bid.")
        elif user["id"] == prop["created_by"]:
            st.caption("You listed this property and cannot bid on it.")
        elif user.get("id") == auction.get("highest_bidder_id"):
            st.success("\U0001f3c6 You are the highest bidder.")
        else:
            chip_cols = st.columns(3)
            for col, amount in zip(chip_cols, _quick_bid_amounts(min_next, increment)):
                col.button(
                    format_inr(amount),
                    key=f"chip_{auction_id}_{amount}",
                    use_container_width=True,
                    on_click=_set_bid_amount,
                    args=(amount_key, amount),
                )

            bid_col, btn_col = st.columns([3, 2])
            amount = bid_col.number_input(
                "Your bid (₹)", min_value=0.01, step=increment or 1000.0, key=amount_key, label_visibility="collapsed"
            )
            if btn_col.button("Place bid", type="primary", key=f"submit_{auction_id}", use_container_width=True):
                try:
                    result = api.place_bid(auction_id, amount, expected_current_price=auction["current_price"])
                except ApiError as exc:
                    st.error(exc.message)
                else:
                    st.toast(f"Your bid of {format_inr(result['bid']['amount'])} is the highest.", icon="\U0001f3c6")
                    st.rerun()

    st.markdown(f"**Live bid history** ({auction['bid_count']})")
    try:
        bids = api.list_bids(auction["id"], limit=25)
    except ApiError:
        bids = []
    if not bids:
        st.caption("No bids yet.")
    else:
        for bid in bids:
            is_me = user and bid["bidder_id"] == user["id"]
            name = "You" if is_me else bid["bidder_name"]
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;padding:6px 4px;'
                f'{"font-weight:700;color:#10b981;" if is_me else ""}">'
                f'<span>{format_inr(bid["amount"])}</span><span>{name}</span>'
                f'<span style="color:#8b9ab3">{format_time(bid["bid_time"])}</span></div>',
                unsafe_allow_html=True,
            )
