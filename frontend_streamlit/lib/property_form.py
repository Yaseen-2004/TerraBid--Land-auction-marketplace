"""Shared property create/edit dialog, used from both the map page and admin page."""

from __future__ import annotations

from datetime import datetime, timedelta

import streamlit as st
from streamlit_folium import st_folium

from lib import api
from lib.api import ApiError
from lib.geo import parse_wkt_preview
from lib.mapview import esri_tile
import folium

SAMPLE_WKT = "POLYGON((77.5946 12.9716, 77.5962 12.9716, 77.5962 12.9727, 77.5946 12.9727, 77.5946 12.9716))"


def _preview_map(wkt_text: str, key: str) -> None:
    rings = parse_wkt_preview(wkt_text)
    if not rings:
        st.caption("Enter a valid WKT polygon to preview it here.")
        return
    center_lat = sum(p[0] for p in rings) / len(rings)
    center_lon = sum(p[1] for p in rings) / len(rings)
    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=16, tiles=None)
    esri_tile("World_Imagery", "Satellite").add_to(fmap)
    folium.Polygon(rings, color="#34d399", weight=3, fill=True, fill_opacity=0.3).add_to(fmap)
    fmap.fit_bounds(rings, padding=(20, 20))
    st_folium(fmap, height=240, use_container_width=True, key=key, returned_objects=[])


def _fields(existing: dict | None, key_prefix: str) -> dict:
    k = lambda name: f"{key_prefix}_{name}"  # noqa: E731

    col1, col2 = st.columns(2)
    with col1:
        title = st.text_input("Property title", value=(existing or {}).get("title", ""), key=k("title"), placeholder="Green Valley Plot")
        location = st.text_input("Location", value=(existing or {}).get("location", ""), key=k("location"), placeholder="Whitefield, Bengaluru")
        base_price = st.number_input(
            "Base price (₹)", min_value=0.0, step=10000.0, value=float((existing or {}).get("base_price") or 0), key=k("price")
        )
        area = st.number_input(
            "Area (sq.ft, optional — computed from the polygon if left at 0)",
            min_value=0.0,
            step=100.0,
            value=float((existing or {}).get("area") or 0),
            key=k("area"),
        )
        description = st.text_area("Description", value=(existing or {}).get("description", ""), key=k("desc"), height=90)
        image_url = st.text_input("Image URL (optional)", value=(existing or {}).get("image_url") or "", key=k("image"))
    with col2:
        wkt_col_header, sample_col = st.columns([3, 1])
        wkt_col_header.markdown("**WKT polygon** (longitude latitude)")
        # Seed once via setdefault rather than passing value= below: Streamlit raises
        # if a widget's session_state key is written to and its value= is also passed
        # in the same run, which is exactly what the sample button below does.
        st.session_state.setdefault(k("wkt"), (existing or {}).get("wkt", ""))
        if sample_col.button("Use sample", key=k("sample")):
            st.session_state[k("wkt")] = SAMPLE_WKT
        wkt = st.text_area(
            "wkt",
            key=k("wkt"),
            height=110,
            label_visibility="collapsed",
            placeholder="POLYGON((77.5946 12.9716, ...))",
        )
        _preview_map(wkt, key=k("preview_map"))

    return {
        "title": title.strip(),
        "location": location.strip(),
        "base_price": base_price,
        "area": area or None,
        "description": description.strip(),
        "image_url": image_url.strip() or None,
        "wkt": wkt.strip(),
    }


def _schedule_fields(key_prefix: str) -> dict | None:
    k = lambda name: f"{key_prefix}_{name}"  # noqa: E731
    schedule_now = st.checkbox("Schedule an auction now", value=True, key=k("schedule"))
    if not schedule_now:
        return None

    st.caption("Times are in your server's local timezone and converted to UTC on submit.")
    now = datetime.now()
    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input("Auction start date", value=now.date(), key=k("start_date"))
        start_time = st.time_input("Start time", value=(now + timedelta(minutes=10)).time().replace(microsecond=0), key=k("start_time"))
    with c2:
        end_date = st.date_input("Auction end date", value=now.date(), key=k("end_date"))
        end_time = st.time_input("End time", value=(now + timedelta(hours=2)).time().replace(microsecond=0), key=k("end_time"))
    increment = st.number_input("Minimum bid increment (₹)", min_value=1.0, step=5000.0, value=50000.0, key=k("increment"))

    start_dt = datetime.combine(start_date, start_time).astimezone()
    end_dt = datetime.combine(end_date, end_time).astimezone()
    return {
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "minimum_increment": increment,
    }


@st.dialog("List a new property", width="large")
def open_create_dialog() -> None:
    st.caption("Boundaries are validated server-side and stored as a PostGIS polygon (EPSG:4326).")
    values = _fields(None, "create")
    schedule = _schedule_fields("create")

    if st.button("Create property", type="primary", key="create_submit"):
        if len(values["title"]) < 3:
            st.error("Title must be at least 3 characters.")
            return
        if not values["wkt"]:
            st.error("A WKT polygon is required.")
            return
        payload = {**values, "auction": schedule}
        try:
            saved = api.create_property(payload)
        except ApiError as exc:
            st.error(exc.message)
            return
        st.session_state["selected_property_id"] = saved["id"]
        st.session_state["properties_cache_bust"] = st.session_state.get("properties_cache_bust", 0) + 1
        st.toast("Property listed on the map.", icon="✅")
        st.rerun()


@st.dialog("Edit property", width="large")
def open_edit_dialog(prop: dict) -> None:
    # Keyed per property: Streamlit widgets only honour value= on their first render per
    # key, so a shared "edit_*" prefix would show a previously edited property's values.
    values = _fields(prop, f"edit_{prop['id']}")

    if st.button("Save changes", type="primary", key="edit_submit"):
        payload = dict(values)
        if payload["wkt"] == prop.get("wkt"):
            payload.pop("wkt")
        if payload["base_price"] == float(prop.get("base_price") or 0):
            payload.pop("base_price")
        if payload["area"] is None:
            payload.pop("area")
        try:
            api.update_property(prop["id"], payload)
        except ApiError as exc:
            st.error(exc.message)
            return
        st.session_state["properties_cache_bust"] = st.session_state.get("properties_cache_bust", 0) + 1
        st.toast("Property updated.", icon="✅")
        st.rerun()
