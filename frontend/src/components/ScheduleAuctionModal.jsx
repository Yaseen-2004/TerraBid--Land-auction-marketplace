import { useState } from 'react';
import Modal from './Modal.jsx';
import { api } from '../api/client.js';
import { useToast } from '../context/ToastContext.jsx';
import { formatINR, isoToLocalInput, localInputToISO, parseAmount } from '../utils/format.js';

export default function ScheduleAuctionModal({ property, onClose, onSaved }) {
  const toast = useToast();
  const [form, setForm] = useState({
    start_time: isoToLocalInput(new Date(Date.now() + 5 * 60 * 1000).toISOString()),
    end_time: isoToLocalInput(new Date(Date.now() + 65 * 60 * 1000).toISOString()),
    starting_price: String(property.base_price),
    minimum_increment: '50000',
  });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const update = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    const starting = parseAmount(form.starting_price);
    const increment = parseAmount(form.minimum_increment);
    if (!starting || !increment) {
      setError('Enter positive amounts for the starting price and increment.');
      return;
    }
    setBusy(true);
    try {
      const auction = await api.createAuction({
        property_id: property.id,
        start_time: localInputToISO(form.start_time),
        end_time: localInputToISO(form.end_time),
        starting_price: starting,
        minimum_increment: increment,
      });
      toast.success('Auction scheduled.');
      onSaved?.(auction);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Schedule auction" subtitle={`${property.title} · base ${formatINR(property.base_price)}`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <div className="row-2">
          <label className="field">
            <span>Start</span>
            <input type="datetime-local" value={form.start_time} onChange={update('start_time')} required />
          </label>
          <label className="field">
            <span>End</span>
            <input type="datetime-local" value={form.end_time} onChange={update('end_time')} required />
          </label>
        </div>
        <div className="row-2">
          <label className="field">
            <span>Starting price (₹)</span>
            <input inputMode="decimal" value={form.starting_price} onChange={update('starting_price')} />
          </label>
          <label className="field">
            <span>Minimum increment (₹)</span>
            <input inputMode="decimal" value={form.minimum_increment} onChange={update('minimum_increment')} />
          </label>
        </div>
        {error && <div className="form-error">{error}</div>}
        <div className="form-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy}>
            {busy ? 'Scheduling…' : 'Schedule'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
