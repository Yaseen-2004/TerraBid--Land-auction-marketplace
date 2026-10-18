/**
 * Backend origin resolution.
 *
 * In the Docker/dev setup the frontend is proxied to the backend on the same
 * origin (nginx or the Vite dev server), so VITE_API_BASE is left unset and
 * every request/socket uses a relative path against window.location.
 *
 * When the frontend and backend are deployed separately (e.g. frontend on
 * Vercel, backend on Railway/Render), set VITE_API_BASE to the backend's full
 * origin at build time, e.g. VITE_API_BASE=https://terrabid-api.up.railway.app
 */
const raw = (import.meta.env.VITE_API_BASE || '').trim().replace(/\/+$/, '');

export const API_BASE = raw;

export const WS_BASE = raw
  ? raw.replace(/^http/, 'ws')
  : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;
