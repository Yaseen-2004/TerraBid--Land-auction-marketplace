import { useCallback, useEffect, useState } from 'react';
import { Route, Routes } from 'react-router-dom';
import AuthModal from './components/AuthModal.jsx';
import Header from './components/Header.jsx';
import { api } from './api/client.js';
import AdminPage from './pages/AdminPage.jsx';
import MapPage from './pages/MapPage.jsx';

const THEME_KEY = 'terrabid.theme';

function initialTheme() {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    /* ignore */
  }
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export default function App() {
  const [theme, setTheme] = useState(initialTheme);
  const [authMode, setAuthMode] = useState(null);
  const [config, setConfig] = useState(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig({}));
  }, []);

  const requireLogin = useCallback(() => setAuthMode('login'), []);

  // Pages render their content inside the shared shell via this layout function.
  const layout = useCallback(
    ({ children, properties, onSearchSelect, onListProperty }) => (
      <div className="app-shell">
        <Header
          properties={properties}
          onSearchSelect={onSearchSelect}
          onListProperty={onListProperty}
          onLogin={() => setAuthMode('login')}
          onRegister={() => setAuthMode('register')}
          theme={theme}
          onToggleTheme={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
        />
        {children}
        {authMode && <AuthModal initialMode={authMode} onClose={() => setAuthMode(null)} />}
      </div>
    ),
    [theme, authMode],
  );
  layout.requireLogin = requireLogin;

  if (!config) return <div className="page-loading">Loading TerraBid…</div>;

  return (
    <Routes>
      <Route path="/" element={<MapPage config={config} layout={layout} />} />
      <Route path="/admin" element={<AdminPage layout={layout} />} />
      <Route path="*" element={<MapPage config={config} layout={layout} />} />
    </Routes>
  );
}
