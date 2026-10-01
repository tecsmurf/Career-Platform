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
| **Styling** | Vanilla CSS (white + sky design system, CSS-3D bubbles) | Full control, no framework or WebGL bloat |
| **HTTP Client** | Axios | Request/response interceptors for JWT |
| **Backend** | FastAPI (Python) | Async, auto-docs, type validation |
| **ORM** | SQLAlchemy 2.0 (async) | Async DB queries, relationship mapping |
| **Database** | PostgreSQL 16 | ACID compliance, production-ready |
| **Auth** | JWT + bcrypt + token-bucket login limiter | Stateless auth, secure hashing, brute-force protection |
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

## 🔐 Login Rate Limiting

`POST /api/auth/login` is protected by **token buckets** (`app/core/token_bucket.py`,
`app/services/login_limiter.py`):

| Bucket | Key | Capacity | Refill |
|---|---|---|---|
| Per account (primary) | submitted email, `.strip().lower()` | 50 attempts | +1 every 1.2 s (≈41.7/min) |
| Per client IP (defence in depth) | client address (IPv6 grouped by /64) | 100 attempts | +1 every 3 s |

- Every login request that reaches credential verification takes one token **before** the
  database lookup or bcrypt runs — successful logins included. Tokens regenerate gradually
  (`floor(elapsed / 1.2 s)`, monotonic clock); there is no fixed-window reset and no lockout
  state, so a legitimate user waits at most ~1.2 s once a burst is spent.
- Empty bucket → `429 {"detail": "Too many login attempts. Please try again shortly."}` with
  `Retry-After` in whole seconds (exposed to the frontend via CORS). The response is identical
  for existing and unknown accounts; bad credentials still get the generic 401. Unknown emails
  also cost a bcrypt check, so response time does not reveal whether an account exists.
- Identifiers are stored and logged only as truncated HMAC-SHA256 digests; at most one
  `login rate limit triggered` log line per bucket per minute.
- **Storage:** `RATE_LIMIT_BACKEND=memory` (default) is atomic within one process — correct for
  the current single-worker Render service. Running several workers/instances? Set
  `RATE_LIMIT_BACKEND=redis` + `REDIS_URL`: the whole bucket update is one Lua script (atomic in
  Redis, using the Redis server clock). If Redis is unreachable it falls back to in-process buckets.
- **Client IP behind a proxy:** set `CLIENT_IP_HEADER` to a header your edge proxy overwrites
  (Render sits behind Cloudflare: `CF-Connecting-IP`). In production the IP bucket stays off until
  this is set, because keying on the proxy's address would throttle every user together.
  `X-Forwarded-For` is never trusted implicitly (its leftmost entries are client-controlled).

The login screen shows a single toast — *"Too many login attempts. Please wait a moment before
trying again."* — and disables the button for the `Retry-After` window. It never retries or
resends the password on its own.

---

## 🎨 Design System

White + sky blue (`#38BDF8` / `#0EA5E9` / `#0284C7`) on `#FFFFFF` / `#F7FAFC`, Inter, soft
layered shadows; no purple/violet/indigo, amber only as the warning colour. Tokens live at the
top of `frontend/src/index.css`.

The signature element is a field of **3D glass bubbles carrying company logos**
(`frontend/src/components/bubbles/`): `CompanyBubble` (the orb), `FloatingBubble` (position,
depth, float), `FloatingCompanyBubble`, `FloatingBubbleField` (renders a config list),
`ParallaxScene` (perspective, mouse parallax, hover) and `BubbleBackground` (fixed backdrop).
Scenes are data in `frontend/src/lib/companies.js`.

- Pure CSS 3D — `perspective`, `translateZ`, transform/opacity animation; no WebGL.
- Depth layers: far bubbles are smaller, fainter, blurred, slower and parallax less.
- Each bubble has its own seeded duration (12–20 s), drift, delay and logo sway.
- Density: 16 on desktop, 10 on tablet, 3–5 on phones (placed in bands clear of the form).
- Decorative only: `pointer-events: none`, `aria-hidden`, always behind content. Hover is
  detected from the pointer position, and only over empty space.
- `prefers-reduced-motion`: float, sway and parallax off; the bubbles stay.
- Logos: [Simple Icons](https://simpleicons.org) (CC0 package) for Google, Apple, Meta, NVIDIA,
  Netflix, Tesla, Uber and Spotify. Brands that asked Simple Icons to remove their marks
  (Microsoft, Amazon, OpenAI, Adobe, IBM, Salesforce, Oracle, LinkedIn) are shown as plain text.
  All names/logos are trademarks of their owners and are decorative only.

---

## 🧪 Testing

```bash
cd backend
pytest tests/ -v                      # 177 tests (auth, jobs, login rate limiter, email)
pip install pymap && pytest tests/    # + 4 real-IMAP-server integration tests
# Redis-backed limiter tests run when `redis-server` is on PATH (or set REDIS_TEST_URL)

cd frontend
npm test                              # 14 unit tests (node:test, no extra dependencies)
```

The email suite covers SSRF (private/internal hosts, DNS rebinding), TLS verification,
credential leakage (responses and logs), cross-user isolation, idempotent sync, malformed and
oversized email, provider failures, throttling, review/accept races, and disconnect.
The rate-limiter suite uses an injected clock (no sleeps): burst of 50, the 51st → 429,
one token per 1.2 s, the cap, concurrent last-token races (threads, asyncio and Redis Lua),
per-account and per-IP independence, and the successful-login policy.

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
