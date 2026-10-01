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
// Exceptions: the login/register calls themselves (a wrong password must show an
// error, not reload the page). Mailbox/IMAP failures never return 401.
const AUTH_ENTRY = ['/auth/login', '/auth/register'];
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

export default api;
