import { useEffect, useRef, useState } from 'react';
import { WS_BASE } from '../api/backend.js';

const MAX_BACKOFF_MS = 30000;
const MAX_SEEN_EVENTS = 500;

/**
 * Subscribes to /ws/auctions/{id}. Handles reconnection with exponential backoff,
 * de-duplicates events by event_id and orders them by (epoch, seq) so replayed,
 * duplicated or out-of-order events never roll the displayed state backwards.
 */
export function useAuctionSocket(auctionId, token) {
  const [auction, setAuction] = useState(null);
  const [bids, setBids] = useState([]);
  const [status, setStatus] = useState('idle');
  const [lastEvent, setLastEvent] = useState(null);
  const [clockOffset, setClockOffset] = useState(0);
  const tokenRef = useRef(token);
  tokenRef.current = token;

  useEffect(() => {
    setAuction(null);
    setBids([]);
    setLastEvent(null);
    if (!auctionId) {
      setStatus('idle');
      return undefined;
    }

    let socket;
    let closedByUs = false;
    let attempt = 0;
    let reconnectTimer;
    let pingTimer;
    let useToken = true;
    let version = { epoch: -1, seq: -1 };
    let seen = new Set();

    const isNewer = (epoch = 0, seq = 0) =>
      epoch > version.epoch || (epoch === version.epoch && seq > version.seq);

    const remember = (eventId) => {
      if (!eventId) return true;
      if (seen.has(eventId)) return false;
      seen.add(eventId);
      if (seen.size > MAX_SEEN_EVENTS) seen = new Set([...seen].slice(-MAX_SEEN_EVENTS / 2));
      return true;
    };

    const handle = (msg) => {
      if (!remember(msg.event_id)) return;
      if (msg.timestamp) setClockOffset(new Date(msg.timestamp).getTime() - Date.now());

      switch (msg.event) {
        case 'SNAPSHOT':
          version = { epoch: msg.epoch ?? 0, seq: msg.seq ?? 0 };
          setAuction(msg.auction);
          setBids(msg.bids || []);
          break;
        case 'BID_ACCEPTED':
          if (!isNewer(msg.epoch, msg.seq)) return;
          version = { epoch: msg.epoch, seq: msg.seq };
          setAuction((a) =>
            a && {
              ...a,
              current_price: msg.current_price,
              min_next_bid: msg.min_next_bid,
              highest_bidder: msg.highest_bidder,
              highest_bidder_id: msg.highest_bidder_id,
              bid_count: msg.bid_count,
              end_time: msg.end_time || a.end_time,
            },
          );
          setBids((list) => (list.some((b) => b.id === msg.bid.id) ? list : [msg.bid, ...list].slice(0, 100)));
          setLastEvent(msg);
          break;
        case 'AUCTION_STARTED':
        case 'AUCTION_ENDED':
        case 'AUCTION_CANCELLED':
          // Lifecycle events carry the full auction and are always authoritative.
          if (isNewer(msg.epoch, msg.seq)) version = { epoch: msg.epoch, seq: msg.seq };
          setAuction(msg.auction);
          setLastEvent(msg);
          break;
        case 'RESYNC':
          if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'sync' }));
          break;
        default:
          break; // HEARTBEAT, PONG
      }
    };

    const connect = () => {
      const t = useToken ? tokenRef.current : null;
      const query = t ? `?token=${encodeURIComponent(t)}` : '';
      setStatus(attempt === 0 ? 'connecting' : 'reconnecting');
      socket = new WebSocket(`${WS_BASE}/ws/auctions/${auctionId}${query}`);

      socket.onopen = () => {
        attempt = 0;
        setStatus('live');
        pingTimer = setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'ping' }));
        }, 20000);
      };
      socket.onmessage = (event) => {
        try {
          handle(JSON.parse(event.data));
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onerror = () => socket.close();
      socket.onclose = (event) => {
        clearInterval(pingTimer);
        if (closedByUs) return;
        if (event.code === 4404) {
          setStatus('not_found');
          return;
        }
        if (event.code === 4401) useToken = false; // fall back to anonymous viewing
        const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt) + Math.random() * 500;
        attempt += 1;
        setStatus('reconnecting');
        reconnectTimer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      closedByUs = true;
      clearTimeout(reconnectTimer);
      clearInterval(pingTimer);
      socket?.close(1000, 'unmount');
    };
  }, [auctionId, token]);

  return { auction, bids, status, lastEvent, clockOffset };
}
