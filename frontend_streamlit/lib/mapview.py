from __future__ import annotations

import folium

from lib.theme import STATUS_META, auction_status_of

_ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services"
_ATTR = "Tiles &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community"


def esri_tile(service: str, name: str) -> folium.TileLayer:
    return folium.TileLayer(
        tiles=f"{_ESRI}/{service}/MapServer/tile/{{z}}/{{y}}/{{x}}",
        attr=_ATTR,
        name=name,
        overlay=False,
        control=False,
    )


def build_map(properties: list[dict], selected_id: int | None) -> folium.Map:
    # A single Satellite base layer only — streamlit-folium's serialization ignores
    # folium.TileLayer's show=False (it calls .addTo() for every registered base layer
    # regardless), so multiple base layers all render stacked with no way to pick one as
    # default. Rather than ship an unreliable layer switcher, always show Satellite.
    fmap = folium.Map(location=[20.5937, 78.9629], zoom_start=5, tiles=None, control_scale=True)
    esri_tile("World_Imagery", "Satellite").add_to(fmap)

    bounds: list[tuple[float, float]] = []
    for prop in properties:
        geometry = prop.get("geometry")
        if not geometry:
            continue
        status = auction_status_of(prop)
        selected = prop["id"] == selected_id
        color = "#ffffff" if selected else STATUS_META.get(status, STATUS_META["NONE"])["color"]

        auction = prop.get("auction")
        price = auction["current_price"] if auction else prop["base_price"]
        tooltip_html = (
            f'<div style="font-family:sans-serif;min-width:160px">'
            f'<strong>{_escape(prop["title"])}</strong><br>'
            f'<span style="color:#64748b;font-size:0.8rem">{_escape(prop["location"])}</span><br>'
            f'<span style="font-size:0.8rem">{STATUS_META.get(status, {}).get("label", status)} '
            f'&middot; ₹{price:,.0f}</span></div>'
        )

        layer = folium.GeoJson(
            geometry,
            style_function=lambda _f, color=color, selected=selected: {
                "color": color,
                "weight": 4 if selected else 2.5,
                "fillColor": color,
                "fillOpacity": 0.45 if selected else 0.28,
                "dashArray": "6 4" if status == "UPCOMING" else None,
            },
            tooltip=folium.Tooltip(tooltip_html),
        )
        layer.add_to(fmap)

        try:
            for lon, lat in geometry["coordinates"][0]:
                bounds.append((lat, lon))
        except (KeyError, IndexError, TypeError):
            pass

    if bounds:
        fmap.fit_bounds(bounds, padding=(40, 40))

    return fmap


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
