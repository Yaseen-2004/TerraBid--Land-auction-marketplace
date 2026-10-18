import { useEffect, useRef, useState } from 'react';
import StatusBadge from './StatusBadge.jsx';
import { api, newIdempotencyKey } from '../api/client.js';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import { useAuctionSocket } from '../hooks/useAuctionSocket.js';
import { useNow } from '../hooks/useNow.js';
import { formatArea, formatDateTime, formatDuration, formatINR, formatTime, parseAmount } from '../utils/format.js';

const CONNECTION_LABEL = {
  idle: 'Offline',
  connecting: 'Connecting…',
  live: 'Live updates',
  reconnecting: 'Reconnecting…',
  not_found: 'Unavailable',
};

export default function AuctionPanel({ property, onClose, onRequireLogin, onAuctionChange }) {
  const { user, token } = useAuth();
  const toast = useToast();
  const auctionId = property.auction?.id;
  const { auction: liveAuction, bids, status: connection, lastEvent, clockOffset } = useAuctionSocket(auctionId, token);
  const auction = liveAuction || property.auction;
  const now = useNow(clockOffset);

  const [amount, setAmount] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [flash, setFlash] = useState(false);
  const inputTouched = useRef(false);

  // Propagate live state to the map and flash the price on every accepted bid.
  useEffect(() => {
    if (liveAuction) onAuctionChange?.(property.id, liveAuction);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveAuction]);

  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.event === 'BID_ACCEPTED') {
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 900);
      if (user && lastEvent.bid?.bidder_id !== user.id && inputTouched.current === false) setAmount('');
      return () => clearTimeout(t);
    }
    if (lastEvent.event === 'AUCTION_ENDED') {
      const won = user && lastEvent.winner_id === user.id;
      toast[won ? 'success' : 'info'](
        won ? `You won ${property.title}!` : `Auction closed${lastEvent.winner_name ? ` — winner: ${lastEvent.winner_name}` : ' with no bids'}.`,
      );
    }
    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastEvent]);

  useEffect(() => {
    setAmount('');
    inputTouched.current = false;
  }, [auctionId]);

  if (!auction) {
    return (
      <aside className="auction-panel glass">
        <PanelHeader property={property} onClose={onClose} />
        <PropertyFacts property={property} />
        <div className="empty-state">No auction is scheduled for this property yet.</div>
      </aside>
    );
  }

  const start = new Date(auction.start_time).getTime();
  const end = new Date(auction.end_time).getTime();
  const isLive = auction.status === 'LIVE' && now < end;
  const isUpcoming = auction.status === 'UPCOMING';
  const isMine = user && property.created_by === user.id;
  const leading = user && auction.highest_bidder_id === user.id;
  const minNext = Number(auction.min_next_bid);
  const increment = Number(auction.minimum_increment);

  const placeBid = async (value) => {
    if (!user) {
      onRequireLogin();
      return;
    }
    const parsed = parseAmount(value);
    if (!parsed) {
      toast.error('Enter a valid bid amount.');
      return;
    }
    if (parsed < minNext) {
      toast.error(`Minimum next bid is ${formatINR(minNext)}.`);
      return;
    }
    setSubmitting(true);
    const key = newIdempotencyKey();
    const send = () => api.placeBid(auction.id, parsed, Number(auction.current_price), key);
    try {
      let result;
      try {
        result = await send();
      } catch (err) {
        if (err.code !== 'NETWORK_ERROR') throw err;
        result = await send(); // safe retry: same idempotency key
      }
      toast.success(`Your bid of ${formatINR(result.bid.amount)} is the highest.`, 'Bid accepted');
      setAmount('');
      inputTouched.current = false;
    } catch (err) {
      toast.error(err.message, 'Bid rejected');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <aside className="auction-panel glass">
      <PanelHeader property={property} onClose={onClose} status={auction.status} />
      <div className="panel-scroll">
        <PropertyFacts property={property} />

        <div className={`price-card ${flash ? 'flash' : ''}`}>
          <span className="eyebrow">{auction.status === 'ENDED' ? 'Final price' : auction.bid_count ? 'Current bid' : 'Starting price'}</span>
          <div className="price">{formatINR(auction.current_price)}</div>
          <div className="price-meta">
            <span>
              {auction.bid_count} bid{auction.bid_count === 1 ? '' : 's'}
            </span>
            <span className={`conn conn-${connection}`}>
              <i /> {CONNECTION_LABEL[connection] || connection}
            </span>
          </div>
        </div>

        <div className="stat-grid">
          <div className="stat">
            <span className="eyebrow">{auction.status === 'ENDED' ? 'Winner' : 'Highest bidder'}</span>
            <strong className={leading ? 'you' : ''}>
              {auction.status === 'ENDED'
                ? auction.winner_name
                  ? `${auction.winner_name}${user && auction.winner_id === user.id ? ' (You)' : ''}`
                  : 'No winner'
                : auction.highest_bidder
                  ? `${auction.highest_bidder}${leading ? ' (You)' : ''}`
                  : '—'}
            </strong>
          </div>
          <div className="stat">
            <span className="eyebrow">Minimum next bid</span>
            <strong>{auction.status === 'LIVE' || isUpcoming ? formatINR(auction.min_next_bid) : '—'}</strong>
          </div>
          <div className="stat stat-wide">
            <span className="eyebrow">
              {isUpcoming ? 'Starts in' : isLive ? 'Auction ends in' : 'Ended'}
            </span>
            <strong className={`countdown ${isLive && end - now < 60000 ? 'urgent' : ''}`}>
              {isUpcoming
                ? formatDuration(start - now)
                : isLive
                  ? formatDuration(end - now)
                  : formatDateTime(auction.end_time)}
            </strong>
          </div>
        </div>

        {isLive && (
          <div className="bid-box">
            {isMine ? (
              <p className="muted">You listed this property and cannot bid on it.</p>
            ) : leading ? (
              <p className="leading-note">🏆 You are the highest bidder.</p>
            ) : null}
            {!isMine && (
              <>
                <div className="quick-bids">
                  {[1, 2, 5].map((multiple) => {
                    const value = minNext + increment * (multiple - 1);
                    return (
                      <button
                        key={multiple}
                        type="button"
                        className="chip"
                        disabled={submitting || leading}
                        onClick={() => {
                          inputTouched.current = true;
                          setAmount(String(value));
                        }}
                      >
                        {formatINR(value)}
                      </button>
                    );
                  })}
                </div>
                <form
                  className="bid-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    placeBid(amount || minNext);
                  }}
                >
                  <div className="input-prefix">
                    <span>₹</span>
                    <input
                      inputMode="decimal"
                      placeholder={String(minNext)}
                      value={amount}
                      onChange={(e) => {
                        inputTouched.current = true;
                        setAmount(e.target.value);
                      }}
                      disabled={submitting || leading}
                      aria-label="Bid amount"
                    />
                  </div>
                  <button className="btn btn-primary btn-bid" disabled={submitting || leading}>
                    {submitting ? 'Placing…' : user ? 'Place bid' : 'Log in to bid'}
                  </button>
                </form>
              </>
            )}
          </div>
        )}
        {isUpcoming && <div className="info-note">Bidding opens {formatDateTime(auction.start_time)}.</div>}
        {auction.status === 'CANCELLED' && <div className="info-note danger">This auction was cancelled.</div>}

        <section className="history">
          <h3>
            Live bid history <span className="muted">({bids.length})</span>
          </h3>
          {bids.length === 0 ? (
            <p className="muted">No bids yet.</p>
          ) : (
            <ul>
              {bids.map((bid, index) => (
                <li key={bid.id} className={`${index === 0 ? 'top' : ''} ${user && bid.bidder_id === user.id ? 'mine' : ''}`}>
                  <span className="amount">{formatINR(bid.amount)}</span>
                  <span className="who">{user && bid.bidder_id === user.id ? 'You' : bid.bidder_name}</span>
                  <span className="when">{formatTime(bid.bid_time)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </aside>
  );
}

function PanelHeader({ property, onClose, status }) {
  return (
    <header className="panel-header">
      {property.image_url && <img src={property.image_url} alt="" className="panel-image" loading="lazy" />}
      <div className="panel-title">
        <div>
          <h2>{property.title}</h2>
          <p className="muted">📍 {property.location}</p>
        </div>
        <div className="panel-actions">
          {status && <StatusBadge status={status} />}
          <button className="icon-btn" onClick={onClose} aria-label="Close panel">
            ✕
          </button>
        </div>
      </div>
    </header>
  );
}

function PropertyFacts({ property }) {
  return (
    <>
      <dl className="facts">
        <div>
          <dt>Area</dt>
          <dd>{formatArea(property.area)}</dd>
        </div>
        <div>
          <dt>Base price</dt>
          <dd>{formatINR(property.base_price)}</dd>
        </div>
        <div>
          <dt>Parcel ID</dt>
          <dd>#{property.id}</dd>
        </div>
      </dl>
      {property.description && <p className="description">{property.description}</p>}
    </>
  );
}
