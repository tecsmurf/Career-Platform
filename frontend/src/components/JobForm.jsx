import { useState } from 'react';
import { STATUSES } from '../constants';
import { AlertCircle } from './icons';
import { getErrorMessage } from '../api';

const EMPTY = {
  company: '', position: '', status: 'applied', location: '',
  job_url: '', salary_min: '', salary_max: '', applied_date: '', notes: '',
};

export default function JobForm({ initialData, onSubmit, onCancel, submitLabel }) {
  const [form, setForm] = useState({
    ...EMPTY,
    applied_date: new Date().toISOString().split('T')[0],
    ...(initialData
      ? {
          company: initialData.company || '',
          position: initialData.position || '',
          status: initialData.status || 'applied',
          location: initialData.location || '',
          job_url: initialData.job_url || '',
          salary_min: initialData.salary_min ?? '',
          salary_max: initialData.salary_max ?? '',
          applied_date: initialData.applied_date || new Date().toISOString().split('T')[0],
          notes: initialData.notes || '',
        }
      : {}),
  });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const update = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    const min = form.salary_min === '' ? null : parseInt(form.salary_min, 10);
    const max = form.salary_max === '' ? null : parseInt(form.salary_max, 10);
    if (min != null && max != null && max < min) {
      setError('Maximum salary can’t be lower than the minimum.');
      return;
    }

    setLoading(true);
    try {
      await onSubmit({
        company: form.company.trim(),
        position: form.position.trim(),
        status: form.status,
        location: form.location.trim() || null,
        job_url: form.job_url.trim() || null,
        salary_min: min,
        salary_max: max,
        applied_date: form.applied_date || null,
        notes: form.notes.trim() || null,
      });
    } catch (err) {
      setError(getErrorMessage(err, 'Something went wrong while saving.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="auth-form" noValidate>
      {error && <div className="alert alert-error"><AlertCircle /><span>{error}</span></div>}

      <div className="form-row">
        <div className="field">
          <label htmlFor="jf-company">Company <span className="req">*</span></label>
          <input id="jf-company" className="input" value={form.company} onChange={update('company')} placeholder="Google" required />
        </div>
        <div className="field">
          <label htmlFor="jf-position">Position <span className="req">*</span></label>
          <input id="jf-position" className="input" value={form.position} onChange={update('position')} placeholder="ML Engineer" required />
        </div>
      </div>

      <div className="form-row">
        <div className="field">
          <label htmlFor="jf-status">Status</label>
          <select id="jf-status" className="select" value={form.status} onChange={update('status')}>
            {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="jf-location">Location</label>
          <input id="jf-location" className="input" value={form.location} onChange={update('location')} placeholder="San Francisco, CA" />
        </div>
      </div>

      <div className="form-row">
        <div className="field">
          <label htmlFor="jf-min">Salary min ($)</label>
          <input id="jf-min" className="input" type="number" min="0" value={form.salary_min} onChange={update('salary_min')} placeholder="100000" />
        </div>
        <div className="field">
          <label htmlFor="jf-max">Salary max ($)</label>
          <input id="jf-max" className="input" type="number" min="0" value={form.salary_max} onChange={update('salary_max')} placeholder="150000" />
        </div>
      </div>

      <div className="form-row">
        <div className="field">
          <label htmlFor="jf-url">Job URL</label>
          <input id="jf-url" className="input" type="url" value={form.job_url} onChange={update('job_url')} placeholder="https://careers.google.com/…" />
        </div>
        <div className="field">
          <label htmlFor="jf-date">Applied date</label>
          <input id="jf-date" className="input" type="date" value={form.applied_date} onChange={update('applied_date')} />
        </div>
      </div>

      <div className="field">
        <label htmlFor="jf-notes">Notes</label>
        <textarea id="jf-notes" className="textarea" value={form.notes} onChange={update('notes')} rows={3} placeholder="Referral from Priya · phone screen scheduled for Tuesday…" />
      </div>

      <div className="form-actions">
        <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? <span className="spinner" /> : (submitLabel || (initialData ? 'Save changes' : 'Add application'))}
        </button>
      </div>
    </form>
  );
}
