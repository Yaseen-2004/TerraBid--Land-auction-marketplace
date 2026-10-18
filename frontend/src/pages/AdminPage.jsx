import { useCallback, useEffect, useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import Modal from '../components/Modal.jsx';
import PolygonPreview from '../components/PolygonPreview.jsx';
import PropertyModal from '../components/PropertyModal.jsx';
import ScheduleAuctionModal from '../components/ScheduleAuctionModal.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import { api } from '../api/client.js';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import { auctionStatusOf, formatArea, formatDateTime, formatINR, formatTime } from '../utils/format.js';
import { parsePolygonWKT } from '../utils/wkt.js';

const TABS = ['Properties', 'Auctions', 'Users'];

export default function AdminPage({ layout }) {
  const { user, loading, isAdmin } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState('Properties');
  const [stats, setStats] = useState(null);
  const [properties, setProperties] = useState([]);
  const [auctions, setAuctions] = useState([]);
  const [users, setUsers] = useState([]);
  const [editing, setEditing] = useState(null);
  const [creating, setCreating] = useState(false);
  const [scheduling, setScheduling] = useState(null);
  const [geometry, setGeometry] = useState(null);
  const [details, setDetails] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [s, p, a, u] = await Promise.all([
        api.adminStats(),
        api.listProperties({ limit: 500, status: ['AVAILABLE', 'IN_AUCTION', 'SOLD', 'UNSOLD', 'WITHDRAWN'] }),
        api.listAuctions({ limit: 500 }),
        api.adminUsers(),
      ]);
      setStats(s);
      setProperties(p);
      setAuctions(a);
      setUsers(u);
    } catch (err) {
      toast.error(err.message, 'Failed to load dashboard');
    }
  }, [toast]);

  useEffect(() => {
    if (isAdmin) refresh();
  }, [isAdmin, refresh]);

  if (loading) return layout({ children: <div className="page-loading">Loading…</div> });
  if (!user || !isAdmin) return <Navigate to="/" replace />;

  const run = async (label, action) => {
    try {
      await action();
      toast.success(label);
      refresh();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const confirmRun = (question, label, action) => window.confirm(question) && run(label, action);

  return layout({
    onListProperty: () => setCreating(true),
    children: (
      <main className="admin">
        <div className="admin-head">
          <div>
            <h1>Admin dashboard</h1>
            <p className="muted">Manage parcels, auctions and users.</p>
          </div>
          <div className="row-actions">
            <button className="btn btn-ghost" onClick={refresh}>
              ↻ Refresh
            </button>
            <button className="btn btn-primary" onClick={() => setCreating(true)}>
              + Create property
            </button>
          </div>
        </div>

        <section className="stats">
          {[
            ['Total properties', stats?.total_properties],
            ['Active auctions', stats?.active_auctions],
            ['Upcoming auctions', stats?.upcoming_auctions],
            ['Completed auctions', stats?.completed_auctions],
            ['Registered users', stats?.registered_users],
            ['Total bids', stats?.total_bids],
            ['Sales value', stats ? formatINR(stats.total_sales_value) : undefined],
          ].map(([label, value]) => (
            <div className="stat-card glass" key={label}>
              <span className="eyebrow">{label}</span>
              <strong>{value ?? '—'}</strong>
            </div>
          ))}
        </section>

        <div className="tabs">
          {TABS.map((t) => (
            <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
              {t}
            </button>
          ))}
        </div>

        <div className="table-wrap glass">
          {tab === 'Properties' && (
            <table>
              <thead>
                <tr>
                  <th>Property</th>
                  <th>Area</th>
                  <th>Base price</th>
                  <th>Status</th>
                  <th>Auction</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {properties.map((p) => {
                  const auctionStatus = auctionStatusOf(p);
                  const canSchedule = !['LIVE', 'UPCOMING'].includes(auctionStatus) && !['SOLD', 'WITHDRAWN'].includes(p.status);
                  return (
                    <tr key={p.id}>
                      <td>
                        <strong>{p.title}</strong>
                        <small className="muted block">
                          #{p.id} · {p.location}
                        </small>
                      </td>
                      <td>{formatArea(p.area)}</td>
                      <td>{formatINR(p.base_price)}</td>
                      <td>
                        <span className="tag">{p.status}</span>
                      </td>
                      <td>
                        <StatusBadge status={auctionStatus} />
                      </td>
                      <td className="actions">
                        <Link className="btn btn-sm btn-ghost" to={`/?property=${p.id}`}>
                          Map
                        </Link>
                        <button className="btn btn-sm btn-ghost" onClick={() => setGeometry(p)}>
                          Geometry
                        </button>
                        <button className="btn btn-sm btn-ghost" onClick={() => setEditing(p)}>
                          Edit
                        </button>
                        {canSchedule && (
                          <button className="btn btn-sm btn-ghost" onClick={() => setScheduling(p)}>
                            Schedule
                          </button>
                        )}
                        <button
                          className="btn btn-sm btn-danger"
                          onClick={() =>
                            confirmRun(`Delete "${p.title}"? This cannot be undone.`, 'Property deleted.', () => api.deleteProperty(p.id))
                          }
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {properties.length === 0 && <EmptyRow cols={6} />}
              </tbody>
            </table>
          )}

          {tab === 'Auctions' && (
            <table>
              <thead>
                <tr>
                  <th>Auction</th>
                  <th>Status</th>
                  <th>Current price</th>
                  <th>Bids</th>
                  <th>Window</th>
                  <th>Winner</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {auctions.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <strong>{a.property?.title}</strong>
                      <small className="muted block">
                        Auction #{a.id} · {a.property?.location}
                      </small>
                    </td>
                    <td>
                      <StatusBadge status={a.status} />
                    </td>
                    <td>{formatINR(a.current_price)}</td>
                    <td>{a.bid_count}</td>
                    <td>
                      <small className="block">{formatDateTime(a.start_time)}</small>
                      <small className="block muted">→ {formatDateTime(a.end_time)}</small>
                    </td>
                    <td>{a.winner_name || (a.status === 'LIVE' ? a.highest_bidder && `${a.highest_bidder} (leading)` : '—')}</td>
                    <td className="actions">
                      <button className="btn btn-sm btn-ghost" onClick={() => setDetails(a)}>
                        Bids
                      </button>
                      {a.status === 'UPCOMING' && (
                        <button className="btn btn-sm btn-ghost" onClick={() => run('Auction started.', () => api.startAuction(a.id))}>
                          Start
                        </button>
                      )}
                      {a.status === 'LIVE' && (
                        <button
                          className="btn btn-sm btn-ghost"
                          onClick={() => confirmRun('End this auction now? The highest bidder will win.', 'Auction ended.', () => api.endAuction(a.id))}
                        >
                          End
                        </button>
                      )}
                      {['UPCOMING', 'LIVE'].includes(a.status) && (
                        <button
                          className="btn btn-sm btn-danger"
                          onClick={() => confirmRun('Cancel this auction? No winner will be declared.', 'Auction cancelled.', () => api.cancelAuction(a.id))}
                        >
                          Cancel
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {auctions.length === 0 && <EmptyRow cols={7} />}
              </tbody>
            </table>
          )}

          {tab === 'Users' && (
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Joined</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <strong>{u.name}</strong>
                      <small className="muted block">{u.email}</small>
                    </td>
                    <td>
                      <select
                        value={u.role}
                        disabled={u.id === user.id}
                        onChange={(e) => run('Role updated.', () => api.updateUser(u.id, { role: e.target.value }))}
                      >
                        {['BIDDER', 'SELLER', 'ADMIN'].map((r) => (
                          <option key={r}>{r}</option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <button
                        className={`btn btn-sm ${u.is_active ? 'btn-ghost' : 'btn-danger'}`}
                        disabled={u.id === user.id}
                        onClick={() => run(u.is_active ? 'User disabled.' : 'User enabled.', () => api.updateUser(u.id, { is_active: !u.is_active }))}
                      >
                        {u.is_active ? 'Active' : 'Disabled'}
                      </button>
                    </td>
                    <td>{formatDateTime(u.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {creating && <PropertyModal onClose={() => setCreating(false)} onSaved={refresh} />}
        {editing && <PropertyModal property={editing} onClose={() => setEditing(null)} onSaved={refresh} />}
        {scheduling && <ScheduleAuctionModal property={scheduling} onClose={() => setScheduling(null)} onSaved={refresh} />}
        {geometry && <GeometryModal property={geometry} onClose={() => setGeometry(null)} />}
        {details && <AuctionDetailsModal auction={details} onClose={() => setDetails(null)} />}
      </main>
    ),
  });
}

function EmptyRow({ cols }) {
  return (
    <tr>
      <td colSpan={cols} className="muted center">
        Nothing here yet.
      </td>
    </tr>
  );
}

function GeometryModal({ property, onClose }) {
  let rings = null;
  try {
    rings = parsePolygonWKT(property.wkt);
  } catch {
    rings = null;
  }
  return (
    <Modal wide title={`Geometry · ${property.title}`} subtitle="Stored as geometry(POLYGON, 4326)" onClose={onClose}>
      <PolygonPreview rings={rings} height={320} />
      <pre className="code-block">{property.wkt}</pre>
    </Modal>
  );
}

function AuctionDetailsModal({ auction, onClose }) {
  const toast = useToast();
  const [bidders, setBidders] = useState([]);
  const [bids, setBids] = useState([]);

  useEffect(() => {
    Promise.all([api.auctionBidders(auction.id), api.listBids(auction.id, { include_rejected: true, limit: 200 })])
      .then(([b, h]) => {
        setBidders(b);
        setBids(h);
      })
      .catch((err) => toast.error(err.message));
  }, [auction.id, toast]);

  return (
    <Modal wide title={`Auction #${auction.id} · ${auction.property?.title}`} subtitle={`Winner: ${auction.winner_name || '—'}`} onClose={onClose}>
      <div className="form-grid">
        <div>
          <h3>Bidders</h3>
          <table className="compact">
            <thead>
              <tr>
                <th>Bidder</th>
                <th>Bids</th>
                <th>Highest</th>
              </tr>
            </thead>
            <tbody>
              {bidders.map((b) => (
                <tr key={b.bidder_id}>
                  <td>
                    {b.name}
                    <small className="muted block">{b.email}</small>
                  </td>
                  <td>{b.bid_count}</td>
                  <td>{formatINR(b.highest_amount)}</td>
                </tr>
              ))}
              {bidders.length === 0 && <EmptyRow cols={3} />}
            </tbody>
          </table>
        </div>
        <div>
          <h3>Bid history (incl. rejected)</h3>
          <table className="compact">
            <thead>
              <tr>
                <th>Amount</th>
                <th>Bidder</th>
                <th>Time</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {bids.map((b) => (
                <tr key={b.id}>
                  <td>{formatINR(b.amount)}</td>
                  <td>{b.bidder_name}</td>
                  <td>{formatTime(b.bid_time)}</td>
                  <td>
                    <span className={`tag ${b.status === 'ACCEPTED' ? 'tag-ok' : 'tag-bad'}`}>{b.rejection_reason || b.status}</span>
                  </td>
                </tr>
              ))}
              {bids.length === 0 && <EmptyRow cols={4} />}
            </tbody>
          </table>
        </div>
      </div>
    </Modal>
  );
}
