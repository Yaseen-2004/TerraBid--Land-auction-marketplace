import L from 'leaflet';

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const ESRI_KEYED = 'https://ibasemaps-api.arcgis.com/arcgis/rest/services';
const ATTRIBUTION = 'Tiles &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community';

function esriLayer(service, apiKey, options = {}) {
  const url = apiKey
    ? `${ESRI_KEYED}/${service}/MapServer/tile/{z}/{y}/{x}?token=${encodeURIComponent(apiKey)}`
    : `${ESRI}/${service}/MapServer/tile/{z}/{y}/{x}`;
  return L.tileLayer(url, { maxZoom: 19, attribution: ATTRIBUTION, ...options });
}

export function createBaseLayers(apiKey) {
  const imagery = esriLayer('World_Imagery', apiKey);
  const labels = esriLayer('Reference/World_Boundaries_and_Places', null, { attribution: '', zIndex: 2 });
  return {
    Satellite: L.layerGroup([imagery, labels]),
    Streets: esriLayer('World_Street_Map', null),
    Topographic: esriLayer('World_Topo_Map', null),
  };
}
