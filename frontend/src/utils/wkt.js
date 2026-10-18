/**
 * Lightweight client-side WKT POLYGON parser used only for the live preview.
 * The server performs the authoritative validation.
 * Returns Leaflet rings ([[lat, lng], ...]) or throws with a friendly message.
 */
export function parsePolygonWKT(input) {
  const text = String(input || '').trim().replace(/^SRID=\d+;/i, '');
  const match = text.match(/^POLYGON\s*\(\s*(\(.*\))\s*\)$/is);
  if (!match) throw new Error('Expected POLYGON((lon lat, lon lat, ...))');

  const ringTexts = match[1].split(/\)\s*,\s*\(/).map((r) => r.replace(/^\(|\)$/g, ''));
  return ringTexts.map((ringText, ringIndex) => {
    const coords = ringText.split(',').map((pair) => {
      const parts = pair.trim().split(/\s+/).map(Number);
      if (parts.length !== 2 || parts.some((n) => !Number.isFinite(n))) {
        throw new Error(`Invalid coordinate "${pair.trim()}" in ring ${ringIndex + 1}`);
      }
      const [lon, lat] = parts;
      if (lon < -180 || lon > 180 || lat < -90 || lat > 90) {
        throw new Error(`Coordinate "${pair.trim()}" is out of range (WKT order is longitude latitude)`);
      }
      return [lat, lon];
    });
    if (coords.length < 4) throw new Error('A polygon ring needs at least 4 coordinates');
    const first = coords[0];
    const last = coords[coords.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) {
      throw new Error('Ring is not closed: first and last coordinates must match');
    }
    return coords;
  });
}

export function sampleWKT(lat = 12.9716, lng = 77.5946) {
  const w = 0.0016;
  const h = 0.0011;
  const pts = [
    [lng, lat],
    [lng + w, lat],
    [lng + w, lat + h],
    [lng, lat + h],
    [lng, lat],
  ];
  return `POLYGON((${pts.map(([x, y]) => `${x.toFixed(6)} ${y.toFixed(6)}`).join(', ')}))`;
}
