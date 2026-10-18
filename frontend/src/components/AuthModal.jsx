import { useState } from 'react';
import Modal from './Modal.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

export default function AuthModal({ initialMode = 'login', onClose }) {
  const auth = useAuth();
  const toast = useToast();
  const [mode, setMode] = useState(initialMode);
  const [form, setForm] = useState({ name: '', email: '', password: '', role: 'BIDDER' });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const update = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user =
        mode === 'login'
          ? await auth.login(form.email, form.password)
          : await auth.register({ name: form.name, email: form.email, password: form.password, role: form.role });
      toast.success(`Welcome, ${user.name}!`);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={mode === 'login' ? 'Welcome back' : 'Create your account'}
      subtitle={mode === 'login' ? 'Log in to place bids in live auctions.' : 'Join to bid on or list land parcels.'}
      onClose={onClose}
    >
      <form className="form" onSubmit={submit}>
        {mode === 'register' && (
          <label className="field">
            <span>Full name</span>
            <input value={form.name} onChange={update('name')} required minLength={2} autoComplete="name" />
          </label>
        )}
        <label className="field">
          <span>Email</span>
          <input type="email" value={form.email} onChange={update('email')} required autoComplete="email" />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={form.password}
            onChange={update('password')}
            required
            minLength={mode === 'register' ? 8 : 1}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          />
          {mode === 'register' && <small className="muted">At least 8 characters with a letter and a digit.</small>}
        </label>
        {mode === 'register' && (
          <div className="field">
            <span>I want to</span>
            <div className="segmented">
              {[
                ['BIDDER', 'Bid on land'],
                ['SELLER', 'Sell land'],
              ].map(([value, label]) => (
                <button
                  type="button"
                  key={value}
                  className={form.role === value ? 'active' : ''}
                  onClick={() => setForm((f) => ({ ...f, role: value }))}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}
        {error && <div className="form-error">{error}</div>}
        <button className="btn btn-primary btn-block" disabled={busy}>
          {busy ? 'Please wait…' : mode === 'login' ? 'Log in' : 'Create account'}
        </button>
        <p className="muted center">
          {mode === 'login' ? "Don't have an account? " : 'Already registered? '}
          <button type="button" className="link" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
            {mode === 'login' ? 'Register' : 'Log in'}
          </button>
        </p>
      </form>
    </Modal>
  );
}
