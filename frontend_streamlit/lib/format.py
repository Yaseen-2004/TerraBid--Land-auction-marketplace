from __future__ import annotations

from datetime import datetime, timezone


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_inr(value: float | int | None) -> str:
    if value is None:
        return "—"
    value = float(value)
    sign = "-" if value < 0 else ""
    whole = _indian_grouping(abs(value))
    if abs(value - round(value)) < 0.005:
        return f"{sign}₹{whole}"
    paise = f"{abs(value) % 1:.2f}"[2:]
    return f"{sign}₹{whole}.{paise}"


def format_compact_inr(value: float | int | None) -> str:
    if value is None:
        return "—"
    value = float(value)
    if value >= 1e7:
        return f"₹{_trim(value / 1e7)} Cr"
    if value >= 1e5:
        return f"₹{_trim(value / 1e5)} L"
    return format_inr(value)


def format_area(value: float | int | None) -> str:
    if not value:
        return "—"
    return f"{int(round(float(value))):,} sq.ft"


def format_area_compact(value: float | int | None) -> str:
    """For narrow layouts (st.metric truncates rather than wraps)."""
    if not value:
        return "—"
    value = float(value)
    if value >= 1e5:
        return f"{_trim(value / 1e5)}L sq.ft"
    if value >= 1e3:
        return f"{_trim(value / 1e3)}K sq.ft"
    return f"{int(round(value))} sq.ft"


def format_datetime(value: str | datetime | None) -> str:
    dt = value if isinstance(value, datetime) else parse_iso(value)
    if dt is None:
        return "—"
    return dt.astimezone().strftime("%d %b %Y, %I:%M %p")


def format_time(value: str | datetime | None) -> str:
    dt = value if isinstance(value, datetime) else parse_iso(value)
    if dt is None:
        return "—"
    return dt.astimezone().strftime("%I:%M:%S %p")


def format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "00:00:00"
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    base = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{days}d {base}" if days else base


def seconds_until(value: str | datetime | None) -> float:
    dt = value if isinstance(value, datetime) else parse_iso(value)
    if dt is None:
        return 0.0
    return (dt - datetime.now(timezone.utc)).total_seconds()


def _trim(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text


def _indian_grouping(value: float) -> str:
    """Format an amount using the Indian numbering system (##,##,###)."""
    int_part = str(int(round(value)))
    if len(int_part) <= 3:
        return int_part
    last3, rest = int_part[-3:], int_part[:-3]
    groups = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return ",".join([*groups, last3])
