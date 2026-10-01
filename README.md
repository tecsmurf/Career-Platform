# 🚀 Career Platform — Full-Stack Job Application Tracker

A full-stack web application that helps job seekers **track, manage, and automate** their job application pipeline. Built with **FastAPI**, **React**, and **PostgreSQL**, plus a **secure email integration** that detects application confirmations, interview invitations, offers, and rejections in your inbox and turns them into suggestions you approve before anything changes.

---

## 🎯 The Problem

Job hunting at scale is chaos:

- You apply to **30+ companies** across LinkedIn, company sites, and referrals
- You lose track of which companies you've heard back from
- **Interview invites sit in your inbox** while your spreadsheet still says "Applied"
- Rejection emails go unnoticed for days
- There's no single source of truth for your entire pipeline

Spreadsheets don't scale. They can't read your email. They can't auto-update.

## 💡 The Solution

This platform gives you:

1. **A centralized dashboard** — every application in one place with real-time stats
2. **Smart search and filtering** — find any application by company, position, or status
3. **Email intelligence** — connect Gmail (App Password) or any IMAP mailbox; job-related emails are detected and extracted into suggestions that you review, edit, and approve (applied → interview → offer/rejected)
4. **Secure multi-user support** — JWT authentication with bcrypt password hashing

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React + Vite)                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │  Login   │  │ Register │  │Dashboard │  │  Job Modal    │   │
│  │  Page    │  │  Page    │  │  Page    │  │  (Add/Edit)   │   │
│  └──────────┘  └──────────┘  └──────────┘  └───────────────┘   │
│       │              │            │  ▲               │          │
│       └──────────────┴────────────┴──┼───────────────┘          │
│                                      │                          │
│              Axios Client (JWT auto-attach)                     │
└──────────────────────────────────────┼──────────────────────────┘
                                       │ HTTP / REST
┌──────────────────────────────────────┼──────────────────────────┐
│                     BACKEND (FastAPI)│                           │
│                                      ▼                          │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    API Router Hub                        │    │
│  │  /api/auth/*    /api/jobs/*    /api/email/*   /api/health│    │
│  └────┬──────────────┬──────────────┬──────────────────────┘    │
│       │              │              │                           │
│       ▼              ▼              ▼                           │
│  ┌─────────┐   ┌──────────┐   ┌──────────────────────────┐     │
│  │  Auth   │   │   Job    │   │  Email integration       │     │
│  │ Service │   │ Service  │   │  • providers (Gmail/IMAP)│     │
│  │ • hash  │   │ • CRUD   │   │  • SSRF guard + TLS pin  │     │
│  │ • JWT   │   │ • search │   │  • sync engine (dedup)   │     │
│  │ • verify│   │ • filter │   │  • classifier (+ AI)     │     │
│  └────┬────┘   └────┬─────┘   │  • review queue          │     │
│       │             │         └──────┬────────────┬──────┘     │
│       ▼             ▼                ▼            │ IMAP over  │
│  ┌──────────────────────────────────────────┐    │ verified   │
│  │ PostgreSQL: users · jobs ·               │    │ TLS (993), │
│  │ email_integrations · email_messages ·    │    │ read-only  │
│  │ job_suggestions                          │    │            │
│  └──────────────────────────────────────────┘    │            │
└──────────────────────────────────────────────────┼────────────┘
                                                   ▼
                                        ┌────────────────────┐
                                        │ Gmail / IMAP inbox │
                                        └────────────────────┘
```

### Data Flow — Email Sync

```
Connect: provider + email + app password
     │  verify first (DNS resolved once, all addresses public, IP pinned,
     │  TLS certificate + host name verified) → only then encrypt & save
     ▼
Sync (throttled, bounded window, ≤100 messages)
     │  EXAMINE INBOX (read-only) → UID SEARCH SINCE → fetch HEADERS
     │  → dedup by Message-ID → pre-filter → fetch first 128 KB (BODY.PEEK)
     ▼
Classify (rules, optional AI) → extract company / position / status
     │  values must literally appear in the email — nothing is invented
     ▼
Suggestion ── "New job: Ramp · AI Engineer (Offer)"  or
              "Update Linear · Product Engineer: Applied → Rejected"
     │
     ▼
You review → edit → Add / Update   (or Ignore) → job saved
```

---

## 🛠️ Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Frontend** | React 19 + Vite | Fast dev server, JSX, component-based UI |
| **Styling** | Vanilla CSS (dark + amber design system) | Full control, no framework bloat |
| **HTTP Client** | Axios | Request/response interceptors for JWT |
| **Backend** | FastAPI (Python) | Async, auto-docs, type validation |
| **ORM** | SQLAlchemy 2.0 (async) | Async DB queries, relationship mapping |
| **Database** | PostgreSQL 16 | ACID compliance, production-ready |
| **Auth** | JWT + bcrypt | Stateless auth, secure password hashing |
| **Validation** | Pydantic v2 | Request/response schema enforcement |
| **Email** | IMAP (verified TLS) + provider layer; optional OpenAI | Works with Gmail App Passwords and any IMAP mailbox |
| **Containerization** | Docker + Docker Compose | One-command local setup |

---

## 📁 Project Structure

```
Career-Platform/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app + CORS + lifespan
│   │   ├── api/
│   │   │   ├── __init__.py            # Router hub
│   │   │   ├── auth.py                # POST /register, /login, GET /me
│   │   │   ├── jobs.py                # Full CRUD + search + filter + stats
│   │   │   ├── email_sync.py          # /api/email/* — connect, sync, review
│   │   │   └── health.py              # Health check
│   │   ├── core/
│   │   │   └── config.py              # Settings from environment variables
│   │   ├── database/
│   │   │   └── connection.py          # Async engine, session factory, init_db
│   │   ├── models/
│   │   │   └── models.py              # User + Job tables (SQLAlchemy ORM)
│   │   ├── schemas/
│   │   │   ├── user.py                # UserCreate, UserResponse, Token
│   │   │   └── job.py                 # JobCreate, JobUpdate, JobResponse
│   │   └── services/
│   │       ├── auth_service.py        # Password hashing, JWT, user lookup
│   │       ├── job_service.py         # Job CRUD business logic
│   │       └── email/                 # Providers, IMAP transport, parsing,
│   │                                  # classifier, AI extractor, sync, review
│   ├── tests/
│   │   ├── test_api.py                # Auth + jobs API tests
│   │   ├── test_email.py              # Email integration: security, sync, review
│   │   └── test_imap_integration.py   # Optional: real IMAP server (needs pymap)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx                    # Route definitions (public/protected)
│   │   ├── api.js                     # Axios client with JWT interceptor
│   │   ├── hooks/useAuth.jsx          # Auth context provider
│   │   ├── pages/
│   │   │   ├── LoginPage.jsx
│   │   │   ├── RegisterPage.jsx
│   │   │   └── DashboardPage.jsx      # Stats + filters + job grid + sync
│   │   ├── components/
│   │   │   ├── JobCard.jsx            # Job display with status badges
│   │   │   ├── JobForm.jsx            # Add/edit modal form
│   │   │   └── email/                 # Email intelligence panel + modals
│   │   └── index.css                  # Dark theme design system
│   ├── Dockerfile
│   └── package.json
├── mcp_servers/
│   └── email_reader/
│       └── server.py                  # Standalone MCP server (not used by the web app)
├── docker-compose.yml                 # PostgreSQL + Backend + Frontend
└── .gitignore
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker Desktop (for PostgreSQL)

### Option 1: Local Development

```bash
# 1. Start PostgreSQL
docker run -d --name career_db \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=career_platform \
  -p 5432:5432 \
  postgres:16-alpine

# 2. Backend
cd backend
python -m venv venv && source venv/bin/activate  # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env   # Edit with your credentials
uvicorn app.main:app --reload --port 8000

# 3. Frontend
cd frontend
npm install
npm run dev
```

### Option 2: Docker Compose

```bash
docker compose up --build
```

Open:
- **Frontend**: http://localhost:5173
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/health

---

## 📡 API Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/auth/register` | Create account | ❌ |
| `POST` | `/api/auth/login` | Get JWT token | ❌ |
| `GET` | `/api/auth/me` | Get profile | ✅ |
| `GET` | `/api/jobs` | List jobs (filter, search, paginate) | ✅ |
| `POST` | `/api/jobs` | Create job | ✅ |
| `GET` | `/api/jobs/{id}` | Get single job | ✅ |
| `PUT` | `/api/jobs/{id}` | Update job | ✅ |
| `DELETE` | `/api/jobs/{id}` | Delete job | ✅ |
| `GET` | `/api/jobs/stats` | Application statistics | ✅ |
| `GET` | `/api/email/status` | Connection + sync status (never credentials) | ✅ |
| `POST` | `/api/email/connect` | Verify mailbox credentials, then store encrypted | ✅ |
| `POST` | `/api/email/test` | Re-verify the stored connection | ✅ |
| `POST` | `/api/email/sync` | Bounded, idempotent sync → suggestions | ✅ |
| `POST` | `/api/email/disconnect` | Revoke credentials (jobs are kept) | ✅ |
| `GET` | `/api/email/messages` | Job-related emails (metadata) | ✅ |
| `GET` | `/api/email/messages/{id}` | One email, plain text | ✅ |
| `GET` | `/api/email/suggestions` | Extracted jobs awaiting review | ✅ |
| `POST` | `/api/email/suggestions/{id}/accept` | Approve (with edits) → create/update job | ✅ |
| `POST` | `/api/email/suggestions/{id}/dismiss` | Ignore a suggestion | ✅ |

### Query Parameters for `GET /api/jobs`

```
?status=interview             # applied | interview | offer | rejected | saved
?search=google                # Search company/position
?page=1&per_page=10           # Pagination
?sort_by=created_at&order=desc # Sorting
```

---

## 📧 Email Integration — How It Works

1. **Connect** (Dashboard → Email intelligence → Connect Gmail / Other IMAP provider).
   Credentials are verified against the real mail server *before* anything is saved, then
   encrypted (Fernet, bound to your account). Your Career Platform login and your mailbox
   credentials are separate systems — mailbox credentials never log you in.
2. **Sync** scans a bounded recent window read-only: nothing is sent, deleted, or marked as read,
   and only job-related emails are kept (other mail is stored as an anonymous dedup key).
3. **Detection** scores each candidate email into application confirmation, interview,
   rejection, offer, recruiter outreach, or job alert, and extracts company, position, salary
   and job link — only values that actually appear in the email. With `OPENAI_API_KEY` set,
   an AI model refines the result; its output is validated the same way.
4. **Review**: each opportunity appears as a suggestion. Edit it, add it to your jobs (or update
   an existing job's status), or ignore it. Nothing changes without your approval.

### Connect Gmail

1. Turn on **2-Step Verification** for your Google account
2. Create an **App Password** at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Make sure **IMAP** is enabled in Gmail settings
4. In the app: **Connect Gmail** → your address + the 16-letter App Password

Your normal Google password is never accepted. Other providers (Fastmail, Zoho, iCloud, Yahoo…)
work via **Other IMAP provider** with their IMAP host and an app-specific password.

---

## 🧪 Testing

```bash
cd backend
pytest tests/ -v                      # 134 tests (auth, jobs, email integration)
pip install pymap && pytest tests/    # + 4 real-IMAP-server integration tests
```

The email suite covers SSRF (private/internal hosts, DNS rebinding), TLS verification,
credential leakage (responses and logs), cross-user isolation, idempotent sync, malformed and
oversized email, provider failures, throttling, review/accept races, and disconnect.

---

## 🔮 Future Improvements

- [ ] **Analytics dashboard** — application funnel visualization, response rate tracking, time-to-response metrics
- [ ] **Calendar integration** — sync interview dates to Google Calendar
- [ ] **Resume tailoring** — auto-customize resume per job using LLM
- [ ] **LinkedIn scraper** — auto-import job postings from LinkedIn saves
- [ ] **Browser extension** — one-click "Save to Career Platform" from any job posting page
- [ ] **Team mode** — share pipeline with career coaches or mentors
- [ ] **Notification system** — push alerts for status changes and follow-up reminders
- [ ] **Mobile app** — React Native companion app

---

## 📄 License

MIT License — free to use, modify, and distribute.
