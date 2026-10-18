import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import AuctionPanel from '../components/AuctionPanel.jsx';
import MapView from '../components/MapView.jsx';
import PropertyModal from '../components/PropertyModal.jsx';
import { api } from '../api/client.js';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import { STATUS_META, auctionStatusOf } from '../utils/format.js';

const FILTERS = [
  ['ACTIVE', 'Live & upcoming'],
  ['LIVE', 'Live'],
  ['UPCOMING', 'Upcoming'],
  ['ENDED', 'Ended'],
  ['ALL', 'All'],
];
const REFRESH_MS = 30000;

function matchesFilter(property, filter) {
  const status = auctionStatusOf(property);
  if (filter === 'ALL') return true;
  if (filter === 'ACTIVE') return status === 'LIVE' || status === 'UPCOMING';
  return status === filter;
}

export default function MapPage({ config, layout }) {
  const { canList } = useAuth();
  const toast = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [properties, setProperties] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('ACTIVE');
  const [showCreate, setShowCreate] = useState(false);

  const selectedId = Number(searchParams.get('property')) || null;

  const load = useCallback(
    async (signal) => {
      try {
        setProperties(await api.listProperties({ limit: 500 }, signal));
      } catch (err) {
        if (err.name !== 'AbortError') toast.error(err.message, 'Could not load properties');
      } finally {
        setLoading(false);
      }
    },
    [toast],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    const id = setInterval(() => load(), REFRESH_MS);
    return () => {
      controller.abort();
      clearInterval(id);
    };
  }, [load]);

  const visible = useMemo(() => {
    const list = properties.filter((p) => matchesFilter(p, filter));
    // Keep the selected parcel visible even if it falls outside the filter.
    const selected = properties.find((p) => p.id === selectedId);
    return selected && !list.includes(selected) ? [...list, selected] : list;
  }, [properties, filter, selectedId]);

  const selected = properties.find((p) => p.id === selectedId) || null;
  const liveCount = properties.filter((p) => auctionStatusOf(p) === 'LIVE').length;

  const select = useCallback(
    (id) => setSearchParams(id ? { property: String(id) } : {}, { replace: false }),
    [setSearchParams],
  );

  const handleAuctionChange = useCallback((propertyId, auction) => {
    setProperties((list) =>
      list.map((p) => (p.id === propertyId ? { ...p, auction: { ...p.auction, ...auction, property: undefined } } : p)),
    );
  }, []);

  return layout({
    properties,
    onSearchSelect: select,
    onListProperty: () => setShowCreate(true),
    children: (
      <div className="map-page">
        <MapView
          properties={visible}
          selectedId={selectedId}
          onSelect={select}
          apiKey={config?.esri_api_key}
          fitKey={`${filter}:${loading}`}
        />

        <div className="map-overlay-top">
          <div className="filter-bar glass">
            {FILTERS.map(([value, label]) => (
              <button key={value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>
                {label}
              </button>
            ))}
          </div>
          <div className="live-pill glass">
            <span className="pulse-dot" /> {liveCount} live auction{liveCount === 1 ? '' : 's'}
          </div>
        </div>

        <div className="legend glass">
          {['LIVE', 'UPCOMING', 'ENDED', 'NONE'].map((s) => (
            <span key={s}>
              <i style={{ background: STATUS_META[s].color }} /> {STATUS_META[s].label}
            </span>
          ))}
        </div>

        {loading && <div className="map-loading glass">Loading parcels…</div>}
        {!loading && visible.length === 0 && (
          <div className="map-empty glass">
            No properties match this filter.
            {canList && (
              <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
                List the first property
              </button>
            )}
          </div>
        )}

        {canList && (
          <button className="fab btn btn-primary" onClick={() => setShowCreate(true)} aria-label="List property">
            +
          </button>
        )}

        {selected && (
          <AuctionPanel
            key={selected.id}
            property={selected}
            onClose={() => select(null)}
            onRequireLogin={layout.requireLogin}
            onAuctionChange={handleAuctionChange}
          />
        )}

        {showCreate && (
          <PropertyModal
            onClose={() => setShowCreate(false)}
            onSaved={(saved) => {
              setProperties((list) => [saved, ...list.filter((p) => p.id !== saved.id)]);
              setFilter('ALL');
              select(saved.id);
            }}
          />
        )}
      </div>
    ),
  });
}
