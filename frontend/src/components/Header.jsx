import { useEffect, useRef, useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import StatusBadge from './StatusBadge.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { auctionStatusOf } from '../utils/format.js';

export default function Header({ properties = [], onSearchSelect, onLogin, onRegister, onListProperty, theme, onToggleTheme }) {
  const { user, logout, isAdmin, canList } = useAuth();
  const [query, setQuery] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    const close = (e) => menuRef.current && !menuRef.current.contains(e.target) && setMenuOpen(false);
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  const q = query.trim().toLowerCase();
  const results = q
    ? properties.filter((p) => p.title.toLowerCase().includes(q) || p.location.toLowerCase().includes(q)).slice(0, 8)
    : [];

  return (
    <header className="topbar glass">
      <Link to="/" className="brand">
        <span className="brand-mark">◆</span>
        <span>
          Terra<b>Bid</b>
        </span>
      </Link>

      {onSearchSelect && (
        <div className="search">
          <input
            type="search"
            placeholder="Search parcels or locations…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search properties"
          />
          {results.length > 0 && (
            <ul className="search-results glass">
              {results.map((p) => (
                <li key={p.id}>
                  <button
                    onClick={() => {
                      onSearchSelect(p.id);
                      setQuery('');
                    }}
                  >
                    <span>
                      <strong>{p.title}</strong>
                      <small>{p.location}</small>
                    </span>
                    <StatusBadge status={auctionStatusOf(p)} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <nav className="topbar-actions">
        <button className="icon-btn" onClick={onToggleTheme} aria-label="Toggle theme" title="Toggle theme">
          {theme === 'dark' ? '☀' : '☾'}
        </button>
        {isAdmin && (
          <NavLink to="/admin" className="btn btn-ghost hide-sm">
            Admin
          </NavLink>
        )}
        {canList && onListProperty && (
          <button className="btn btn-ghost hide-sm" onClick={onListProperty}>
            + List property
          </button>
        )}
        {user ? (
          <div className="profile" ref={menuRef}>
            <button className="avatar" onClick={() => setMenuOpen((o) => !o)} aria-label="Profile menu">
              {user.name.slice(0, 1).toUpperCase()}
            </button>
            {menuOpen && (
              <div className="menu glass">
                <div className="menu-head">
                  <strong>{user.name}</strong>
                  <small>{user.email}</small>
                  <span className="role">{user.role}</span>
                </div>
                <Link to="/" onClick={() => setMenuOpen(false)}>
                  Map
                </Link>
                {isAdmin && (
                  <Link to="/admin" onClick={() => setMenuOpen(false)}>
                    Admin dashboard
                  </Link>
                )}
                {canList && onListProperty && (
                  <button
                    onClick={() => {
                      setMenuOpen(false);
                      onListProperty();
                    }}
                  >
                    List property
                  </button>
                )}
                <button
                  className="danger"
                  onClick={() => {
                    setMenuOpen(false);
                    logout();
                  }}
                >
                  Log out
                </button>
              </div>
            )}
          </div>
        ) : (
          <>
            <button className="btn btn-ghost" onClick={onLogin}>
              Log in
            </button>
            <button className="btn btn-primary hide-sm" onClick={onRegister}>
              Sign up
            </button>
          </>
        )}
      </nav>
    </header>
  );
}
