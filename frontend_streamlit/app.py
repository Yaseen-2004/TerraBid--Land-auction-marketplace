from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager

import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "terrabid_demo.sqlite3"

st.set_page_config(
    page_title="TerraBid | Land Auction Marketplace",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---- Visual system ---------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
:root { --ink:#eaf0fb; --muted:#9aa8bd; --panel:#111b2b; --line:#27364c; --accent:#69e0b1; }
html, body, [class*="css"] { font-family:'DM Sans',sans-serif; }
.stApp { background: radial-gradient(circle at 15% 0%, #172b43 0%, #0a1220 45%, #080e18 100%); color:var(--ink); }
h1,h2,h3 { font-family:'Manrope',sans-serif; letter-spacing:-.035em; }
.block-container { padding-top:1.7rem; padding-bottom:3rem; max-width:1500px; }
div[data-testid="stMetric"] { background:rgba(17,27,43,.82); border:1px solid var(--line); padding:16px 18px; border-radius:16px; }
div[data-testid="stMetricLabel"] { color:#a7b5c9; }
div[data-testid="stMetricValue"] { color:#f4f7ff; }
section[data-testid="stSidebar"] { background:#0c1523; border-right:1px solid #26364c; }
div[data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--line)!important; border-radius:16px!important; }
div.stButton > button[kind="primary"] { background:#69e0b1; color:#07131a; border:0; font-weight:700; }
div.stButton > button { border-radius:10px; }
.eyebrow { color:#69e0b1; text-transform:uppercase; letter-spacing:.16em; font-size:.72rem; font-weight:800; }
.hero { padding:26px 28px; border:1px solid #2b4059; border-radius:22px; background:linear-gradient(115deg,rgba(25,48,70,.95),rgba(14,24,39,.92)); margin-bottom:20px; }
.hero h1 { font-size:2.25rem; margin:.3rem 0 .4rem; }
.hero p { color:#a9bad0; margin:0; max-width:720px; }
.pill { display:inline-block; border:1px solid #2d725e; background:#133a32; color:#8cf0c9; border-radius:99px; padding:4px 10px; font-size:.75rem; font-weight:700; }
.small-muted { color:#9aa8bd; font-size:.86rem; }
</style>
""", unsafe_allow_html=True)

# ---- Local database: no Docker, no API, no external database required -----
@contextmanager
def db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS properties (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, location TEXT NOT NULL,
            district TEXT NOT NULL, area_acres REAL NOT NULL, base_price REAL NOT NULL,
            latitude REAL NOT NULL, longitude REAL NOT NULL, description TEXT NOT NULL,
            land_type TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS auctions (
            id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL, status TEXT NOT NULL,
            start_time TEXT NOT NULL, end_time TEXT NOT NULL, starting_price REAL NOT NULL,
            current_price REAL NOT NULL, minimum_increment REAL NOT NULL DEFAULT 25000,
            bid_count INTEGER NOT NULL DEFAULT 0, highest_bidder TEXT,
            FOREIGN KEY(property_id) REFERENCES properties(id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS bids (
            id INTEGER PRIMARY KEY AUTOINCREMENT, auction_id INTEGER NOT NULL,
            bidder TEXT NOT NULL, amount REAL NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(auction_id) REFERENCES auctions(id))""")
        existing = conn.execute("SELECT COUNT(*) AS n FROM properties").fetchone()["n"]
        if existing == 0:
            now = datetime.now()
            props = [
                (1,"Devanahalli Growth Corridor Plot","Devanahalli, Bengaluru Rural","Bengaluru Rural",1.20,7800000,13.2478,77.7132,"Strategic parcel near the airport growth corridor. Demo listing for evaluating land discovery and auction workflows.","Residential",1),
                (2,"Hoskote Industrial Land Parcel","Hoskote, Bengaluru Rural","Bengaluru Rural",2.75,15200000,13.0707,77.7982,"Large industrial-use demo parcel with access toward the eastern logistics belt.","Industrial",1),
                (3,"Kanakapura Greenfield Estate","Kanakapura, Ramanagara","Ramanagara",3.40,9100000,12.5466,77.4200,"Greenfield land parcel in a developing corridor. Please verify zoning and title independently.","Agricultural",0),
                (4,"Nelamangala Highway Frontage","Nelamangala, Bengaluru Rural","Bengaluru Rural",0.95,6400000,13.0997,77.3936,"Highway-frontage sample listing intended for demonstration of parcel comparison.","Commercial",1),
                (5,"Anekal Residential Extension","Anekal, Bengaluru Urban","Bengaluru Urban",1.60,11200000,12.7111,77.6956,"Residential expansion-area sample parcel. All details are illustrative demo data.","Residential",0),
                (6,"Ramanagara Orchard Land","Ramanagara, Ramanagara","Ramanagara",4.20,8500000,12.7150,77.2800,"Agricultural land sample with a larger acreage profile.","Agricultural",1),
                (7,"Yelahanka North Development Site","Yelahanka, Bengaluru Urban","Bengaluru Urban",0.70,13400000,13.1007,77.5963,"Compact development-site demo listing in north Bengaluru.","Commercial",1),
                (8,"Doddaballapur Farm Parcel","Doddaballapur, Bengaluru Rural","Bengaluru Rural",5.10,7200000,13.2927,77.5370,"Rural agricultural sample parcel for browsing and filtering.","Agricultural",0),
            ]
            conn.executemany("INSERT INTO properties VALUES (?,?,?,?,?,?,?,?,?,?,?)", props)
            auctions = [
                (1,1,"LIVE",(now-timedelta(minutes=25)).isoformat(timespec="seconds"),(now+timedelta(hours=2,minutes=20)).isoformat(timespec="seconds"),7800000,8050000,25000,3,"Aarav Demo"),
                (2,2,"UPCOMING",(now+timedelta(hours=5)).isoformat(timespec="seconds"),(now+timedelta(hours=9)).isoformat(timespec="seconds"),15200000,15200000,50000,0,None),
                (3,3,"LIVE",(now-timedelta(minutes=40)).isoformat(timespec="seconds"),(now+timedelta(hours=1,minutes=10)).isoformat(timespec="seconds"),9100000,9350000,25000,2,"Priya Demo"),
                (4,4,"ENDED",(now-timedelta(days=2)).isoformat(timespec="seconds"),(now-timedelta(days=2)+timedelta(hours=4)).isoformat(timespec="seconds"),6400000,6900000,25000,5,"Kabir Demo"),
                (5,5,"UPCOMING",(now+timedelta(days=1)).isoformat(timespec="seconds"),(now+timedelta(days=1,hours=4)).isoformat(timespec="seconds"),11200000,11200000,25000,0,None),
                (6,6,"LIVE",(now-timedelta(minutes=5)).isoformat(timespec="seconds"),(now+timedelta(hours=3)).isoformat(timespec="seconds"),8500000,8500000,25000,0,None),
                (7,7,"UPCOMING",(now+timedelta(days=2)).isoformat(timespec="seconds"),(now+timedelta(days=2,hours=4)).isoformat(timespec="seconds"),13400000,13400000,50000,0,None),
                (8,8,"ENDED",(now-timedelta(days=5)).isoformat(timespec="seconds"),(now-timedelta(days=5)+timedelta(hours=4)).isoformat(timespec="seconds"),7200000,7450000,25000,4,"Meera Demo"),
            ]
            conn.executemany("INSERT INTO auctions VALUES (?,?,?,?,?,?,?,?,?,?)", auctions)
            sample_bids = [
                (1,"Aarav Demo",7900000,(now-timedelta(minutes=20)).isoformat(timespec="seconds")),
                (1,"Priya Demo",8000000,(now-timedelta(minutes=12)).isoformat(timespec="seconds")),
                (1,"Aarav Demo",8050000,(now-timedelta(minutes=6)).isoformat(timespec="seconds")),
                (3,"Priya Demo",9200000,(now-timedelta(minutes=18)).isoformat(timespec="seconds")),
                (3,"Kabir Demo",9350000,(now-timedelta(minutes=7)).isoformat(timespec="seconds")),
                (4,"Kabir Demo",6900000,(now-timedelta(days=2)+timedelta(hours=3)).isoformat(timespec="seconds")),
                (8,"Meera Demo",7450000,(now-timedelta(days=5)+timedelta(hours=3)).isoformat(timespec="seconds")),
            ]
            conn.executemany("INSERT INTO bids (auction_id,bidder,amount,created_at) VALUES (?,?,?,?)", sample_bids)

def load_data():
    with db() as conn:
        return pd.read_sql_query("""SELECT p.*, a.id AS auction_id, a.status, a.start_time, a.end_time,
            a.starting_price, a.current_price, a.minimum_increment, a.bid_count, a.highest_bidder
            FROM properties p LEFT JOIN auctions a ON p.id=a.property_id ORDER BY p.id""", conn)

def money(value):
    return "₹" + f"{float(value):,.0f}"

def fmt_time(value):
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return value or "—"

def place_bid(auction_id, bidder, amount):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        auction = conn.execute("SELECT * FROM auctions WHERE id=?", (int(auction_id),)).fetchone()
        if not auction:
            return False, "Auction not found."
        now = datetime.now()
        start, end = datetime.fromisoformat(auction["start_time"]), datetime.fromisoformat(auction["end_time"])
        if auction["status"] != "LIVE" or not (start <= now <= end):
            return False, "This auction is not currently open for bidding."
        minimum = float(auction["current_price"]) + float(auction["minimum_increment"])
        if float(amount) < minimum:
            return False, f"Your bid must be at least {money(minimum)}."
        conn.execute("INSERT INTO bids (auction_id,bidder,amount,created_at) VALUES (?,?,?,?)",
                     (int(auction_id), bidder.strip(), float(amount), now.isoformat(timespec="seconds")))
        conn.execute("UPDATE auctions SET current_price=?, bid_count=bid_count+1, highest_bidder=? WHERE id=?",
                     (float(amount), bidder.strip(), int(auction_id)))
    return True, "Demo bid recorded successfully."

init_db()

# ---- Sidebar ---------------------------------------------------------------
with st.sidebar:
    st.markdown("# 🌍 TerraBid")
    st.caption("Land auction marketplace")
    st.markdown('<span class="pill">LOCAL DEMO MODE</span>', unsafe_allow_html=True)
    st.write("")
    page = st.radio("Navigate", ["Marketplace", "Auction activity", "About this demo"], label_visibility="collapsed")
    st.divider()
    bidder_name = st.text_input("Demo bidder name", value=st.session_state.get("bidder_name", "Guest Bidder"))
    st.session_state["bidder_name"] = bidder_name
    st.caption("Changes are saved locally to SQLite.")
    st.divider()
    st.caption("No Docker • No API server • No cloud database")

data = load_data()
active_count = int((data["status"] == "LIVE").sum())
upcoming_count = int((data["status"] == "UPCOMING").sum())
total_value = float(data["base_price"].sum())

if page == "Marketplace":
    st.markdown("""
    <div class="hero">
      <div class="eyebrow">Land intelligence · Transparent auctions</div>
      <h1>Find your next piece of land.</h1>
      <p>Explore sample land parcels, compare locations and acreage, and try the auction workflow using realistic demo listings. All sample records are illustrative.</p>
    </div>
    """, unsafe_allow_html=True)

    k1,k2,k3,k4 = st.columns(4)
    k1.metric("Listed parcels", f"{len(data)}", "Sample inventory")
    k2.metric("Live auctions", active_count, "Open in demo")
    k3.metric("Upcoming", upcoming_count, "Scheduled")
    k4.metric("Listed value", money(total_value), "Base prices combined")

    f1,f2,f3,f4 = st.columns([1.5,1.2,1.2,1.3])
    query = f1.text_input("Search", placeholder="Location or parcel name")
    types = ["All types"] + sorted(data["land_type"].unique().tolist())
    land_type = f2.selectbox("Land type", types)
    status_options = ["All statuses", "LIVE", "UPCOMING", "ENDED"]
    status = f3.selectbox("Auction status", status_options)
    min_acres, max_acres = float(data["area_acres"].min()), float(data["area_acres"].max())
    acre_range = f4.slider("Area (acres)", min_acres, max_acres, (min_acres, max_acres), step=0.1)

    filtered = data.copy()
    if query:
        filtered = filtered[filtered.apply(lambda r: query.lower() in str(r["title"]).lower() or query.lower() in str(r["location"]).lower() or query.lower() in str(r["district"]).lower(), axis=1)]
    if land_type != "All types":
        filtered = filtered[filtered["land_type"] == land_type]
    if status != "All statuses":
        filtered = filtered[filtered["status"] == status]
    filtered = filtered[filtered["area_acres"].between(acre_range[0], acre_range[1])]
    map_col, list_col = st.columns([1.15, 1], gap="large")

    with map_col:
        st.subheader("Parcel map")
        fmap = folium.Map(location=[12.95,77.55], zoom_start=9, tiles="CartoDB dark_matter", control_scale=True)
        colors = {"LIVE":"#62e6b2", "UPCOMING":"#ffca70", "ENDED":"#9aa8bd"}
        for _, r in filtered.iterrows():
            color = colors.get(r["status"], "#9aa8bd")
            folium.CircleMarker(
                location=[r["latitude"],r["longitude"]], radius=9,
                color=color, fill=True, fill_color=color, fill_opacity=.85,
                tooltip=f'{r["title"]} · {r["area_acres"]:.2f} acres',
                popup=f'<b>{r["title"]}</b><br>{r["location"]}<br>{money(r["current_price"] or r["base_price"])}'
            ).add_to(fmap)
        st_folium(fmap, height=510, use_container_width=True, returned_objects=[], key="parcel_map")
        st.caption("Map markers show approximate sample locations, not surveyed property boundaries.")

    with list_col:
        st.subheader(f"Available parcels · {len(filtered)}")
        if filtered.empty:
            st.info("No parcels match these filters. Try widening your search.")
        for _, r in filtered.iterrows():
            with st.container(border=True):
                left, right = st.columns([3,1])
                left.markdown(f"**{r['title']}**")
                left.caption(f"📍 {r['location']} · {r['area_acres']:.2f} acres · {r['land_type']}")
                badge = {"LIVE":"🟢 LIVE","UPCOMING":"🟠 UPCOMING","ENDED":"⚪ ENDED"}.get(r["status"],"No auction")
                right.markdown(f"**{badge}**")
                price = r["current_price"] if pd.notna(r["current_price"]) else r["base_price"]
                left.markdown(f"### {money(price)}")
                left.markdown(f'<span class="small-muted">{"Verified demo record" if r["verified"] else "Verification pending"} · {int(r["bid_count"] or 0)} bids</span>', unsafe_allow_html=True)
                with st.expander("View details & bid"):
                    st.write(r["description"])
                    st.write(f"**Auction starts:** {fmt_time(r['start_time'])}")
                    st.write(f"**Auction ends:** {fmt_time(r['end_time'])}")
                    st.write(f"**Minimum increment:** {money(r['minimum_increment'] or 0)}")
                    if r["status"] == "LIVE":
                        minimum = float(r["current_price"]) + float(r["minimum_increment"])
                        with st.form(f"bid_form_{int(r['auction_id'])}"):
                            st.caption(f"Minimum next bid: {money(minimum)}")
                            amount = st.number_input("Your bid (₹)", min_value=minimum, value=minimum, step=float(r["minimum_increment"]), key=f"bid_{int(r['auction_id'])}")
                            submit = st.form_submit_button("Place demo bid", type="primary", use_container_width=True)
                        if submit:
                            if not bidder_name.strip():
                                st.error("Enter a demo bidder name in the sidebar.")
                            else:
                                ok, msg = place_bid(int(r["auction_id"]), bidder_name, amount)
                                (st.success if ok else st.error)(msg)
                                if ok:
                                    st.rerun()
                    elif r["status"] == "UPCOMING":
                        st.info("Bidding opens when the scheduled start time is reached.")
                    else:
                        st.info("This sample auction has ended.")

    st.divider()
    st.caption("Demo disclaimer: listings, prices, bidder names, verification labels and bid history are synthetic. Do not use this app to make real estate or financial decisions.")

elif page == "Auction activity":
    st.markdown('<div class="eyebrow">Market pulse</div><h1>Auction activity</h1>', unsafe_allow_html=True)
    with db() as conn:
        bids = pd.read_sql_query("""SELECT b.id, p.title AS parcel, b.bidder, b.amount, b.created_at
            FROM bids b JOIN auctions a ON b.auction_id=a.id JOIN properties p ON p.id=a.property_id
            ORDER BY b.created_at DESC""", conn)
    a,b,c = st.columns(3)
    a.metric("Recorded demo bids", len(bids))
    c.metric("Unique demo bidders", int(bids["bidder"].nunique()) if not bids.empty else 0)
    b.metric("Highest demo bid", money(bids["amount"].max()) if not bids.empty else "₹0")
    if bids.empty:
        st.info("No bids have been recorded yet.")
    else:
        view = bids.copy()
        view["amount"] = view["amount"].map(money)
        view["created_at"] = view["created_at"].map(fmt_time)
        view.columns = ["Bid #","Parcel","Bidder","Amount","Time"]
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.subheader("Bids by parcel")
        chart = bids.groupby("parcel", as_index=False).size().rename(columns={"size":"Bid count"})
        st.bar_chart(chart, x="parcel", y="Bid count", use_container_width=True)

elif page == "About this demo":
    st.markdown('<div class="eyebrow">Project notes</div><h1>About TerraBid Demo</h1>', unsafe_allow_html=True)
    st.markdown("""
    TerraBid is a Streamlit demonstration of a land parcel marketplace and auction workflow.

    **Included in this no-Docker edition**
    - Local SQLite database created automatically on first launch
    - Eight pre-populated example parcels around Bengaluru and nearby districts
    - Live, upcoming and ended sample auctions
    - Search and filters for land type, location, acreage and auction status
    - Interactive map markers
    - Bid placement with minimum-increment validation
    - Local bid history and activity charts
    - Persistent data between app restarts

    **What this edition is not**
    - It does not connect to the original FastAPI/PostgreSQL/Redis backend.
    - It is not suitable for real-money bidding, legal title verification, or public production auctions.
    - There is no secure user authentication in demo mode; bidder names are labels only.

    For real deployment, replace demo mode with a secured backend, identity provider, managed database, authorization controls, audit logs, and tested concurrency safeguards.
    """)
    with st.container(border=True):
        st.subheader("Reset sample data")
        st.write("Resetting deletes local demo bids and restores the original sample inventory.")
        confirm = st.checkbox("I understand this will delete all local demo bids.")
        if st.button("Reset demo database", type="primary", disabled=not confirm):
            if DB_PATH.exists():
                DB_PATH.unlink()
            init_db()
            st.success("Sample data restored.")
            st.rerun()

st.markdown("---")
st.markdown('<div class="small-muted">TerraBid · Local demo build · Sample data only · No Docker required</div>', unsafe_allow_html=True)
