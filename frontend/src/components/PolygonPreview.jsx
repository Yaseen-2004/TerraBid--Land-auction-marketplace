import { useEffect, useRef } from 'react';
import L from 'leaflet';
import { createBaseLayers } from './tiles.js';

/** Small map rendering Leaflet rings ([[lat,lng],...]) for WKT previews. */
export default function PolygonPreview({ rings, height = 220 }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const layerRef = useRef(null);

  useEffect(() => {
    const map = L.map(containerRef.current, { attributionControl: false, zoomControl: true }).setView([12.9716, 77.5946], 13);
    createBaseLayers(null).Satellite.addTo(map);
    mapRef.current = map;
    setTimeout(() => map.invalidateSize(), 50);
    return () => map.remove();
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (layerRef.current) {
      map.removeLayer(layerRef.current);
      layerRef.current = null;
    }
    if (rings?.length) {
      layerRef.current = L.polygon(rings, { color: '#34d399', weight: 3, fillOpacity: 0.3 }).addTo(map);
      map.fitBounds(layerRef.current.getBounds(), { padding: [20, 20], maxZoom: 18 });
    }
  }, [rings]);

  return <div ref={containerRef} className="preview-map" style={{ height }} />;
}
