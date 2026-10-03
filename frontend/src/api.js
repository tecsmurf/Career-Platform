import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: `${API_URL}/api`,
  headers: { 'Content-Type': 'application/json' },
});

// Attach the platform JWT to every request (single auth mechanism for the whole app).
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// A 401 means the *platform session* is invalid or expired → sign out.
// Exceptions: the sign-in / sign-up / code calls themselves (a wrong password
// or code must show an error, not reload the page). Mailbox/IMAP failures
// never return 401.
const AUTH_ENTRY = [
  '/auth/login', '/auth/register', '/auth/verify-email', '/auth/resend-verification',
  '/auth/forgot-password', '/auth/reset-password', '/auth/config',
];
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    const url = error.config?.url || '';
    const hadToken = !!error.config?.headers?.Authorization;
    if (status === 401 && hadToken && !AUTH_ENTRY.some((p) => url.startsWith(p))) {
      localStorage.removeItem('token');
      if (window.location.pathname !== '/login') window.location.assign('/login');
    }
    return Promise.reject(error);
  }
);

/**
 * Turn any API error into a short, human message. Handles FastAPI's string
 * details, our {code, message} details, 422 validation arrays, network errors
 * and server errors — so components never render raw objects.
 */
export function getErrorMessage(err, fallback = 'Something went wrong. Please try again.') {
  if (!err?.response) {
    if (err?.code === 'ECONNABORTED') return 'The request took too long. Please try again.';
    return 'Can’t reach the server. Check your connection and try again.';
  }
  const { status, data } = err.response;
  const detail = data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.message) return detail.message;
  if (Array.isArray(detail) && detail.length) {
    const msg = String(detail[0]?.msg || '').replace(/^Value error, /, '');
    return msg ? msg.charAt(0).toUpperCase() + msg.slice(1) : fallback;
  }
  if (status === 429) return 'Too many attempts. Please wait a moment and try again.';
  if (status >= 500) return 'Something went wrong on our side. Please try again.';
  return fallback;
}

export function getErrorCode(err) {
  const detail = err?.response?.data?.detail;
  return detail && typeof detail === 'object' && !Array.isArray(detail) ? detail.code : undefined;
}

// Auth endpoints
export const authAPI = {
  register: (data) => api.post('/auth/register', data),
  login: (data) => {
    const formData = new URLSearchParams();
    formData.append('username', data.email);
    formData.append('password', data.password);
    return api.post('/auth/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
  },
  getMe: () => api.get('/auth/me'),
  config: () => api.get('/auth/config'),
  // `ticket` comes from sign-up or from a sign-in that needs verification.
  verifyEmail: (ticket, code) => api.post('/auth/verify-email', { ticket, code }),
  resendVerification: (ticket) => api.post('/auth/resend-verification', { ticket }),
  // Reset codes are bound to the ticket returned here; pass it back to resend.
  forgotPassword: (email, ticket) => api.post('/auth/forgot-password', ticket ? { email, ticket } : { email }),
  resetPassword: (ticket, code, newPassword) =>
    api.post('/auth/reset-password', { ticket, code, new_password: newPassword }),
};

// Job endpoints
export const jobsAPI = {
  list: (params) => api.get('/jobs', { params }),
  get: (id) => api.get(`/jobs/${id}`),
  create: (data) => api.post('/jobs', data),
  update: (id, data) => api.put(`/jobs/${id}`, data),
  delete: (id) => api.delete(`/jobs/${id}`),
  stats: () => api.get('/jobs/stats'),
};

// Email integration endpoints
export const emailAPI = {
  getStatus: () => api.get('/email/status'),
  connect: (data) => api.post('/email/connect', data, { timeout: 60000 }),
  testConnection: () => api.post('/email/test', null, { timeout: 60000 }),
  sync: (data) => api.post('/email/sync', data || {}, { timeout: 120000 }),
  disconnect: (data) => api.post('/email/disconnect', data || {}),
  listMessages: (params) => api.get('/email/messages', { params }),
  getMessage: (id) => api.get(`/email/messages/${id}`),
  listSuggestions: (params) => api.get('/email/suggestions', { params }),
  acceptSuggestion: (id, data) => api.post(`/email/suggestions/${id}/accept`, data || {}),
  dismissSuggestion: (id) => api.post(`/email/suggestions/${id}/dismiss`),
};

// Apply Assistant — job intelligence and tailored applications. Nothing here
// sends email or submits forms: "approve" freezes a copy-ready final version.
export const applyAPI = {
  status: () => api.get('/apply/status'),
  overview: () => api.get('/apply/overview'),
  getProfile: () => api.get('/apply/profile'),
  saveProfile: (data) => api.put('/apply/profile', data),
  getResume: () => api.get('/apply/resume'),
  saveResume: (text) => api.put('/apply/resume', { text }),
  uploadResume: (file) => {
    const form = new FormData();
    form.append('file', file);
    return api.post('/apply/resume/upload', form, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60000 });
  },
  listPostings: (params) => api.get('/apply/postings', { params }),
  addPosting: (data) => api.post('/apply/postings', data, { timeout: 60000 }),
  getPosting: (id) => api.get(`/apply/postings/${id}`),
  refreshPosting: (id) => api.post(`/apply/postings/${id}/refresh`, null, { timeout: 60000 }),
  trackPosting: (id) => api.post(`/apply/postings/${id}/track`),
  archivePosting: (id) => api.post(`/apply/postings/${id}/archive`),
  restorePosting: (id) => api.post(`/apply/postings/${id}/restore`),
  prepare: (id) => api.post(`/apply/postings/${id}/prepare`, null, { timeout: 90000 }),
  listPackages: (status) => api.get('/apply/packages', { params: { status } }),
  getPackage: (id) => api.get(`/apply/packages/${id}`),
  editPackage: (id, baseHash, edits) => api.patch(`/apply/packages/${id}`, { base_hash: baseHash, edits }),
  approvePackage: (id, payloadHash) => api.post(`/apply/packages/${id}/approve`, { payload_hash: payloadHash }),
  rejectPackage: (id, reason) => api.post(`/apply/packages/${id}/reject`, { reason: reason || null }),
  markSent: (id, channel) => api.post(`/apply/packages/${id}/mark-sent`, { channel }),
  listSources: () => api.get('/apply/sources'),
  addSource: (data) => api.post('/apply/sources', data),
  deleteSource: (id) => api.delete(`/apply/sources/${id}`),
  runSource: (id) => api.post(`/apply/sources/${id}/run`, null, { timeout: 90000 }),
};

export default api;
