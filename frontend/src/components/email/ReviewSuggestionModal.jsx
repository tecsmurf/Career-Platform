import Modal from '../Modal';
import JobForm from '../JobForm';
import { AlertTriangle, Mail } from '../icons';
import { confidenceInfo, senderLabel, timeAgo } from '../../lib/emailUi';

/** Edit extracted fields before anything is saved. Nothing unknown is pre-filled. */
export default function ReviewSuggestionModal({ suggestion: s, onClose, onAccept, onViewEmail }) {
  const missing = [!s.company && 'company', !s.position && 'position'].filter(Boolean);
  const initial = {
    company: s.company || '',
    position: s.position || '',
    status: s.status,
    location: s.location || '',
    job_url: s.job_url || '',
    salary_min: s.salary_min ?? '',
    salary_max: s.salary_max ?? '',
    applied_date: s.applied_date || '',
    notes: '',
  };

  return (
    <Modal title="Review & add to your jobs" onClose={onClose}>
      {s.email && (
        <div className="review-source">
          <Mail />
          <div>
            <div><b>{senderLabel(s.email)}</b> <span className="dim">· {timeAgo(s.email.received_at)} · {confidenceInfo(s.confidence).label.toLowerCase()}</span></div>
            <div className="muted">“{s.email.subject || '(no subject)'}”</div>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => onViewEmail(s.email.id)}>View email</button>
        </div>
      )}
      {missing.length > 0 && (
        <div className="alert alert-warn" role="note">
          <AlertTriangle />
          <span>We couldn’t find the {missing.join(' or ')} in this email, so {missing.length > 1 ? 'they’re' : 'it’s'} left blank. Please fill {missing.length > 1 ? 'them' : 'it'} in.</span>
        </div>
      )}
      <JobForm initialData={initial} submitLabel="Add to jobs" onSubmit={onAccept} onCancel={onClose} />
    </Modal>
  );
}
