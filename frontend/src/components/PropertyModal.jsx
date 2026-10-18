import { useMemo, useState } from 'react';
import Modal from './Modal.jsx';
import PolygonPreview from './PolygonPreview.jsx';
import { api } from '../api/client.js';
import { useToast } from '../context/ToastContext.jsx';
import { isoToLocalInput, localInputToISO, parseAmount } from '../utils/format.js';
import { parsePolygonWKT, sampleWKT } from '../utils/wkt.js';

function defaultForm(property) {
  const start = new Date(Date.now() + 10 * 60 * 1000);
  const end = new Date(Date.now() + 2 * 60 * 60 * 1000);
  return {
    title: property?.title || '',
    description: property?.description || '',
    location: property?.location || '',
    base_price: property?.base_price ? String(property.base_price) : '',
    area: property?.area ? String(property.area) : '',
    image_url: property?.image_url || '',
    wkt: property?.wkt || '',
    schedule: !property,
    start_time: isoToLocalInput(start.toISOString()),
    end_time: isoToLocalInput(end.toISOString()),
    minimum_increment: '50000',
  };
}

/** Create or edit a property. `property` present => edit mode (auction scheduling is managed separately). */
export default function PropertyModal({ property, onClose, onSaved }) {
  const toast = useToast();
  const editing = Boolean(property);
  const [form, setForm] = useState(() => defaultForm(property));
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState(null);
  const [busy, setBusy] = useState(false);

  const update = (field) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [field]: value }));
    setErrors((errs) => ({ ...errs, [field]: undefined }));
  };

  const preview = useMemo(() => {
    if (!form.wkt.trim()) return { rings: null, error: null };
    try {
      return { rings: parsePolygonWKT(form.wkt), error: null };
    } catch (err) {
      return { rings: null, error: err.message };
    }
  }, [form.wkt]);

  const validate = () => {
    const errs = {};
    if (form.title.trim().length < 3) errs.title = 'Title must be at least 3 characters.';
    if (form.location.trim().length < 2) errs.location = 'Location is required.';
    if (!parseAmount(form.base_price)) errs.base_price = 'Enter a positive price.';
    if (form.area && !parseAmount(form.area)) errs.area = 'Area must be a positive number.';
    if (!form.wkt.trim()) errs.wkt = 'WKT polygon is required.';
    else if (preview.error) errs.wkt = preview.error;
    if (!editing && form.schedule) {
      const start = new Date(form.start_time);
      const end = new Date(form.end_time);
      if (Number.isNaN(start.getTime())) errs.start_time = 'Choose a start time.';
      if (Number.isNaN(end.getTime()) || end <= start) errs.end_time = 'End time must be after the start time.';
      if (!parseAmount(form.minimum_increment)) errs.minimum_increment = 'Enter a positive increment.';
    }
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const submit = async (e) => {
    e.preventDefault();
    setFormError(null);
    if (!validate()) return;

    const payload = {
      title: form.title.trim(),
      description: form.description.trim(),
      location: form.location.trim(),
      base_price: parseAmount(form.base_price),
      area: form.area ? parseAmount(form.area) : null,
      image_url: form.image_url.trim() || null,
      wkt: form.wkt.trim(),
    };
    if (editing) {
      // Only send locked fields when they actually changed.
      if (payload.wkt === property.wkt) delete payload.wkt;
      if (payload.base_price === Number(property.base_price)) delete payload.base_price;
      if (payload.area === null) delete payload.area;
    } else {
      payload.auction = form.schedule
        ? {
            start_time: localInputToISO(form.start_time),
            end_time: localInputToISO(form.end_time),
            minimum_increment: parseAmount(form.minimum_increment),
          }
        : null;
    }

    setBusy(true);
    try {
      const saved = editing ? await api.updateProperty(property.id, payload) : await api.createProperty(payload);
      toast.success(editing ? 'Property updated.' : 'Property listed on the map.');
      onSaved?.(saved);
      onClose();
    } catch (err) {
      const fieldErrors = {};
      (Array.isArray(err.details) ? err.details : []).forEach((d) => {
        const key = String(d.field || '').split('.').pop();
        if (key) fieldErrors[key] = d.message;
      });
      setErrors(fieldErrors);
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const fieldError = (name) => errors[name] && <small className="field-error">{errors[name]}</small>;

  return (
    <Modal
      wide
      title={editing ? 'Edit property' : 'List a new property'}
      subtitle="Boundaries are validated and stored as a PostGIS polygon (EPSG:4326)."
      onClose={onClose}
    >
      <form className="form property-form" onSubmit={submit} noValidate>
        <div className="form-grid">
          <div className="form-col">
            <label className="field">
              <span>Property title</span>
              <input value={form.title} onChange={update('title')} placeholder="Green Valley Plot" />
              {fieldError('title')}
            </label>
            <label className="field">
              <span>Location</span>
              <input value={form.location} onChange={update('location')} placeholder="Whitefield, Bengaluru" />
              {fieldError('location')}
            </label>
            <div className="row-2">
              <label className="field">
                <span>Base price (₹)</span>
                <input inputMode="decimal" value={form.base_price} onChange={update('base_price')} placeholder="2500000" />
                {fieldError('base_price')}
              </label>
              <label className="field">
                <span>Area (sq.ft, optional)</span>
                <input inputMode="decimal" value={form.area} onChange={update('area')} placeholder="Auto from polygon" />
                {fieldError('area')}
              </label>
            </div>
            <label className="field">
              <span>Description</span>
              <textarea rows={3} value={form.description} onChange={update('description')} />
              {fieldError('description')}
            </label>
            <label className="field">
              <span>Image URL (optional)</span>
              <input value={form.image_url} onChange={update('image_url')} placeholder="https://…" />
              {fieldError('image_url')}
            </label>

            {!editing && (
              <fieldset className="fieldset">
                <label className="checkbox">
                  <input type="checkbox" checked={form.schedule} onChange={update('schedule')} />
                  <span>Schedule an auction now</span>
                </label>
                {form.schedule && (
                  <>
                    <div className="row-2">
                      <label className="field">
                        <span>Auction start</span>
                        <input type="datetime-local" value={form.start_time} onChange={update('start_time')} />
                        {fieldError('start_time')}
                      </label>
                      <label className="field">
                        <span>Auction end</span>
                        <input type="datetime-local" value={form.end_time} onChange={update('end_time')} />
                        {fieldError('end_time')}
                      </label>
                    </div>
                    <label className="field">
                      <span>Minimum bid increment (₹)</span>
                      <input inputMode="decimal" value={form.minimum_increment} onChange={update('minimum_increment')} />
                      {fieldError('minimum_increment')}
                    </label>
                  </>
                )}
              </fieldset>
            )}
          </div>

          <div className="form-col">
            <label className="field">
              <span className="field-label-row">
                WKT polygon (longitude latitude)
                <button type="button" className="link" onClick={() => setForm((f) => ({ ...f, wkt: sampleWKT() }))}>
                  Use sample
                </button>
              </span>
              <textarea
                className="mono"
                rows={6}
                value={form.wkt}
                onChange={update('wkt')}
                placeholder="POLYGON((77.5946 12.9716, 77.5962 12.9716, 77.5962 12.9727, 77.5946 12.9727, 77.5946 12.9716))"
                spellCheck={false}
              />
              {errors.wkt ? (
                <small className="field-error">{errors.wkt}</small>
              ) : preview.rings ? (
                <small className="field-ok">✓ Polygon parsed — the server will validate geometry.</small>
              ) : null}
            </label>
            <PolygonPreview rings={preview.rings} height={260} />
          </div>
        </div>

        {formError && <div className="form-error">{formError}</div>}
        <div className="form-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy}>
            {busy ? 'Saving…' : editing ? 'Save changes' : 'Create property'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
