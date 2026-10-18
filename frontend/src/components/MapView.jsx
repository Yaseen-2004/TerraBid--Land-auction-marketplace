import { useEffect, useRef } from 'react';
import L from 'leaflet';
import { createBaseLayers } from './tiles.js';
import { STATUS_META, auctionStatusOf, formatCompactINR } from '../utils/format.js';

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

function styleFor(property, selected) {
  const color = STATUS_META[auctionStatusOf(property)].color;
  return {
    color: selected ? '#ffffff' : color,
    weight: selected ? 4 : 2.5,
    fillColor: color,
    fillOpacity: selected ? 0.45 : 0.28,
    dashArray: auctionStatusOf(property) === 'UPCOMING' ? '6 4' : null,
  };
}

function tooltipHtml(property) {
  const status = auctionStatusOf(property);
  const price = property.auction ? property.auction.current_price : property.base_price;
  return `<div class="map-tip">
    <strong>${escapeHtml(property.title)}</strong>
    <span>${escapeHtml(property.location)}</span>
    <span class="map-tip-row"><em class="dot" style="background:${STATUS_META[status].color}"></em>${STATUS_META[status].label} · ${formatCompactINR(price)}</span>
  </div>`;
}

export default function MapView({ properties, selectedId, onSelect, apiKey, fitKey }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const groupRef = useRef(null);
  const layersRef = useRef(new Map());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // Initialise the map once.
  useEffect(() => {
    const map = L.map(containerRef.current, { zoomControl: false, worldCopyJump: true }).setView([20.5937, 78.9629], 5);
    const baseLayers = createBaseLayers(apiKey);
    baseLayers.Satellite.addTo(map);
    L.control.layers(baseLayers, null, { position: 'bottomleft' }).addTo(map);
    L.control.zoom({ position: 'bottomleft' }).addTo(map);
    L.control.scale({ position: 'bottomright', imperial: false }).addTo(map);
    groupRef.current = L.featureGroup().addTo(map);
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      layersRef.current.clear();
    };
  }, [apiKey]);

  // Sync polygons with the property list.
  useEffect(() => {
    const group = groupRef.current;
    if (!group) return;
    const layers = layersRef.current;
    const ids = new Set(properties.map((p) => p.id));

    for (const [id, layer] of layers) {
      if (!ids.has(id)) {
        group.removeLayer(layer);
        layers.delete(id);
      }
    }
    properties.forEach((property) => {
      const selected = property.id === selectedId;
      let layer = layers.get(property.id);
      if (!layer) {
        layer = L.geoJSON(property.geometry);
        layer.on('click', (e) => {
          L.DomEvent.stopPropagation(e);
          onSelectRef.current(property.id);
        });
        layer.bindTooltip('', { sticky: true, direction: 'top', className: 'map-tooltip' });
        group.addLayer(layer);
        layers.set(property.id, layer);
      }
      layer.setStyle(styleFor(property, selected));
      layer.setTooltipContent(tooltipHtml(property));
      if (selected) layer.bringToFront();
    });
  }, [properties, selectedId]);

  // Fit to all visible properties when the set changes (initial load / filter change).
  useEffect(() => {
    const map = mapRef.current;
    const group = groupRef.current;
    if (!map || !group || group.getLayers().length === 0) return;
    map.fitBounds(group.getBounds(), { padding: [60, 60], maxZoom: 16 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey]);

  // Focus the selected parcel, leaving room for the side panel on wide screens.
  useEffect(() => {
    const map = mapRef.current;
    const layer = layersRef.current.get(selectedId);
    if (!map || !layer) return;
    const wide = window.innerWidth > 900;
    map.flyToBounds(layer.getBounds(), {
      paddingTopLeft: [40, 40],
      paddingBottomRight: wide ? [460, 40] : [40, window.innerHeight * 0.55],
      maxZoom: 17,
      duration: 0.8,
    });
  }, [selectedId]);

  return <div ref={containerRef} className="map" />;
}
