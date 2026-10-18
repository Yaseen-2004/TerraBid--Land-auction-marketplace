import { API_BASE } from './backend.js';

const TOKEN_KEY = 'terrabid.token';

export class ApiError extends Error {
  constructor(message, status, code, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode) — session-only auth */
  }
}

const SESSION_ERRORS = new Set(['TOKEN_EXPIRED', 'INVALID_TOKEN', 'UNAUTHORIZED']);

async function request(path, { method = 'GET', body, headers = {}, query, signal } = {}) {
  const url = new URL(`${API_BASE}/api${path}`, window.location.origin);
  if (query) {
    Object.entries(query).forEach(([key, value]) => {
      if (value === undefined || value === null || value === '') return;
      if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, v));
      else url.searchParams.set(key, value);
    });
  }

  const finalHeaders = { Accept: 'application/json', ...headers };
  if (body !== undefined) finalHeaders['Content-Type'] = 'application/json';
  const token = getToken();
  if (token) finalHeaders.Authorization = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(url, {
      method,
      headers: finalHeaders,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    throw new ApiError('Network error — check your connection and try again.', 0, 'NETWORK_ERROR');
  }

  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const code = data?.error_code || 'HTTP_ERROR';
    if (response.status === 401 && token && SESSION_ERRORS.has(code)) {
      window.dispatchEvent(new CustomEvent('auth:expired'));
    }
    throw new ApiError(data?.message || response.statusText || 'Request failed', response.status, code, data?.details);
  }
  return data;
}

export const api = {
  // auth
  register: (payload) => request('/auth/register', { method: 'POST', body: payload }),
  login: (email, password) => request('/auth/login', { method: 'POST', body: { email, password } }),
  me: () => request('/auth/me'),

  // system
  config: () => request('/config'),

  // properties
  listProperties: (query, signal) => request('/properties', { query, signal }),
  getProperty: (id) => request(`/properties/${id}`),
  createProperty: (payload) => request('/properties', { method: 'POST', body: payload }),
  updateProperty: (id, payload) => request(`/properties/${id}`, { method: 'PUT', body: payload }),
  deleteProperty: (id) => request(`/properties/${id}`, { method: 'DELETE' }),

  // auctions
  listAuctions: (query) => request('/auctions', { query }),
  getAuction: (id) => request(`/auctions/${id}`),
  createAuction: (payload) => request('/auctions', { method: 'POST', body: payload }),
  updateAuction: (id, payload) => request(`/auctions/${id}`, { method: 'PUT', body: payload }),
  startAuction: (id) => request(`/auctions/${id}/start`, { method: 'PUT' }),
  endAuction: (id) => request(`/auctions/${id}/end`, { method: 'PUT' }),
  cancelAuction: (id) => request(`/auctions/${id}/cancel`, { method: 'PUT' }),

  // bids
  placeBid: (auctionId, amount, expectedCurrentPrice, idempotencyKey) =>
    request(`/auctions/${auctionId}/bid`, {
      method: 'POST',
      body: { amount, expected_current_price: expectedCurrentPrice },
      headers: { 'Idempotency-Key': idempotencyKey },
    }),
  listBids: (auctionId, query) => request(`/auctions/${auctionId}/bids`, { query }),

  // admin
  adminStats: () => request('/admin/stats'),
  adminUsers: () => request('/admin/users', { query: { limit: 500 } }),
  updateUser: (id, payload) => request(`/admin/users/${id}`, { method: 'PATCH', body: payload }),
  auctionBidders: (auctionId) => request(`/admin/auctions/${auctionId}/bidders`),
};

export function newIdempotencyKey() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}
