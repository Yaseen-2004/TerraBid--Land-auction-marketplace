const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const inrPrecise = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 });
const number = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });

export function formatINR(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  const n = Number(value);
  return Number.isInteger(n) ? inr.format(n) : inrPrecise.format(n);
}

export function formatCompactINR(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2).replace(/\.00$/, '')} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2).replace(/\.00$/, '')} L`;
  return inr.format(n);
}

export function formatArea(value) {
  if (!value) return '—';
  return `${number.format(value)} sq.ft`;
}

export function formatDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}

export function formatTime(iso) {
  return new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function formatDuration(ms) {
  if (ms <= 0) return '00:00:00';
  const total = Math.floor(ms / 1000);
  const days = Math.floor(total / 86400);
  const h = String(Math.floor((total % 86400) / 3600)).padStart(2, '0');
  const m = String(Math.floor((total % 3600) / 60)).padStart(2, '0');
  const s = String(total % 60).padStart(2, '0');
  return days > 0 ? `${days}d ${h}:${m}:${s}` : `${h}:${m}:${s}`;
}

export function parseAmount(input) {
  const cleaned = String(input ?? '').replace(/[₹,\s]/g, '');
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  const n = Number(cleaned);
  return n > 0 ? n : null;
}

/** Convert a <input type="datetime-local"> value (local time) to an ISO UTC string. */
export function localInputToISO(value) {
  return value ? new Date(value).toISOString() : null;
}

/** Convert an ISO string to a datetime-local input value in the user's timezone. */
export function isoToLocalInput(iso) {
  const d = iso ? new Date(iso) : new Date();
  const offset = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - offset).toISOString().slice(0, 16);
}

export const STATUS_META = {
  LIVE: { label: 'Live', tone: 'live', color: '#22c55e' },
  UPCOMING: { label: 'Upcoming', tone: 'upcoming', color: '#f59e0b' },
  ENDED: { label: 'Ended', tone: 'ended', color: '#94a3b8' },
  CANCELLED: { label: 'Cancelled', tone: 'cancelled', color: '#ef4444' },
  NONE: { label: 'No auction', tone: 'none', color: '#38bdf8' },
};

export function auctionStatusOf(property) {
  return property?.auction?.status || 'NONE';
}
