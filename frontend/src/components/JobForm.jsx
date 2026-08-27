import { useState } from 'react';

const STATUS_OPTIONS = ['applied', 'interviewing', 'offer', 'rejected', 'withdrawn'];

export default function JobForm({ initialData, onSubmit, onCancel }) {
  const [form, setForm] = useState({
    company: initialData?.company || '',
    position: initialData?.position || '',
    status: initialData?.status || 'applied',
    location: initialData?.location || '',
    job_url: initialData?.job_url || '',
    salary_min: initialData?.salary_min || '',
    salary_max: initialData?.salary_max || '',
    applied_date: initialData?.applied_date || new Date().toISOString().split('T')[0],
    notes: initialData?.notes || '',
  });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const update = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const data = { ...form };
      // Convert empty strings to null for optional fields
      if (!data.salary_min) data.salary_min = null;
      else data.salary_min = parseInt(data.salary_min);
      if (!data.salary_max) data.salary_max = null;
      else data.salary_max = parseInt(data.salary_max);
      if (!data.job_url) data.job_url = null;
      if (!data.location) data.location = null;
      if (!data.notes) data.notes = null;
      await onSubmit(data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to save');
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="job-form">
      {error && <div className="error-msg">{error}</div>}
      <div className="form-row">
        <div className="form-group">
          <label>Company *</label>
          <input type="text" value={form.company} onChange={update('company')} placeholder="Google" required />
        </div>
        <div className="form-group">
          <label>Position *</label>
          <input type="text" value={form.position} onChange={update('position')} placeholder="ML Engineer" required />
        </div>
      </div>
      <div className="form-row">
        <div className="form-group">
          <label>Status</label>
          <select value={form.status} onChange={update('status')}>
            {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
          </select>
        </div>
        <div className="form-group">
          <label>Location</label>
          <input type="text" value={form.location} onChange={update('location')} placeholder="San Francisco, CA" />
        </div>
      </div>
      <div className="form-row">
        <div className="form-group">
          <label>Salary Min ($)</label>
          <input type="number" value={form.salary_min} onChange={update('salary_min')} placeholder="100000" />
        </div>
        <div className="form-group">
          <label>Salary Max ($)</label>
          <input type="number" value={form.salary_max} onChange={update('salary_max')} placeholder="150000" />
        </div>
      </div>
      <div className="form-group">
        <label>Job URL</label>
        <input type="url" value={form.job_url} onChange={update('job_url')} placeholder="https://careers.google.com/..." />
      </div>
      <div className="form-group">
        <label>Applied Date</label>
        <input type="date" value={form.applied_date} onChange={update('applied_date')} />
      </div>
      <div className="form-group">
        <label>Notes</label>
        <textarea value={form.notes} onChange={update('notes')} placeholder="Referral from John, phone screen scheduled..." rows={3} />
      </div>
      <div className="form-actions">
        <button type="button" onClick={onCancel} className="btn btn-ghost">Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? 'Saving...' : (initialData ? 'Update' : 'Add Job')}
        </button>
      </div>
    </form>
  );
}
