"""Shared status colors/labels, matching the original React app's legend."""

STATUS_META = {
    "LIVE": {"label": "Live", "color": "#22c55e"},
    "UPCOMING": {"label": "Upcoming", "color": "#f59e0b"},
    "ENDED": {"label": "Ended", "color": "#94a3b8"},
    "CANCELLED": {"label": "Cancelled", "color": "#ef4444"},
    "NONE": {"label": "No auction", "color": "#38bdf8"},
}


def auction_status_of(prop: dict) -> str:
    auction = prop.get("auction")
    return auction["status"] if auction else "NONE"


def status_badge_html(status: str) -> str:
    meta = STATUS_META.get(status, {"label": status, "color": "#94a3b8"})
    dot = (
        '<span style="display:inline-block;width:7px;height:7px;border-radius:50%;'
        f'background:{meta["color"]};margin-right:6px;"></span>'
    )
    return (
        f'<span style="display:inline-flex;align-items:center;padding:2px 10px;border-radius:999px;'
        f'background:{meta["color"]}26;color:{meta["color"]};font-size:0.75rem;font-weight:700;'
        f'text-transform:uppercase;letter-spacing:0.04em;">{dot}{meta["label"]}</span>'
    )
