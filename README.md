# 🚀 Career Platform — Full-Stack Job Application Tracker

A full-stack web application that helps job seekers **track, manage, and automate** their job application pipeline. Built with **FastAPI**, **React**, **PostgreSQL**, and an **MCP-powered email sync** that automatically detects interview invitations, offers, and rejections from your inbox and updates application statuses in real-time.

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
3. **Automated email sync** — an MCP server connects to your Gmail, detects job-related emails, and auto-updates application statuses (applied → interviewing → offer/rejected)
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
│  ┌─────────┐   ┌──────────┐   ┌──────────┐                     │
│  │  Auth   │   │   Job    │   │  Email   │                     │
│  │ Service │   │ Service  │   │  Sync    │                     │
│  │         │   │          │   │ Service  │                     │
│  │ • hash  │   │ • CRUD   │   │          │                     │
│  │ • JWT   │   │ • search │   │ • match  │                     │
│  │ • verify│   │ • filter │   │ • update │                     │
│  └────┬────┘   └────┬─────┘   └────┬─────┘                     │
│       │             │              │                            │
│       ▼             ▼              │                            │
│  ┌─────────────────────────┐       │     MCP Protocol (stdio)   │
│  │     PostgreSQL          │       │              │              │
│  │  ┌───────┐  ┌───────┐  │       │              ▼              │
│  │  │ users │  │ jobs  │  │       │    ┌──────────────────┐     │
│  │  └───────┘  └───────┘  │       │    │  Email MCP Server│     │
│  └─────────────────────────┘       │    │                  │     │
│                                    │    │  • fetch_emails  │     │
│                                    │    │  • search_emails │     │
│                                    │    │  • scan_job_mail │     │
│                                    │    └────────┬─────────┘     │
│                                    │             │               │
│                                    └─────────────┘               │
│                                          │ IMAP                  │
└──────────────────────────────────────────┼───────────────────────┘
                                           │
                                    ┌──────▼──────┐
                                    │   Gmail     │
                                    │   Inbox     │
                                    └─────────────┘
```

### Data Flow — Email Auto-Sync

```
Gmail Inbox
     │
     │ IMAP (SSL)
     ▼
Email MCP Server ──scan_job_emails──▶ Pattern Match
     │                                     │
     │                          ┌──────────┴──────────┐
     │                          │ Regex patterns for:  │
     │                          │ • Interview invites  │
     │                          │ • Offer letters      │
     │                          │ • Rejections         │
     │                          │ • Application acks   │
     │                          └──────────┬──────────┘
     │                                     │
     ▼                                     ▼
Email Sync Service ◀── detected signals ───┘
     │
     │ Match email company → job in database
     │ (exact match → fuzzy match → AI match)
     │
     ▼
Database UPDATE ── status: "applied" → "interviewing"
     │
     ▼
Frontend notification: "Google — ML Engineer: applied → interviewing"
```

---

## 🛠️ Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Frontend** | React 19 + Vite | Fast dev server, JSX, component-based UI |
| **Styling** | Vanilla CSS (dark theme + glassmorphism) | Full control, no framework bloat |
| **HTTP Client** | Axios | Request/response interceptors for JWT |
| **Backend** | FastAPI (Python) | Async, auto-docs, type validation |
| **ORM** | SQLAlchemy 2.0 (async) | Async DB queries, relationship mapping |
| **Database** | PostgreSQL 16 | ACID compliance, production-ready |
| **Auth** | JWT + bcrypt | Stateless auth, secure password hashing |
| **Validation** | Pydantic v2 | Request/response schema enforcement |
| **Email** | MCP Server + IMAP | Standard protocol for tool integration |
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
│   │   │   ├── email_sync.py          # POST /sync, /preview
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
│   │       └── email_sync_service.py  # Email-to-job matching + auto-update
│   ├── tests/
│   │   └── test_api.py                # 13 integration tests
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
│   │   │   └── JobForm.jsx            # Add/edit modal form
│   │   └── index.css                  # Dark theme design system
│   ├── Dockerfile
│   └── package.json
├── mcp_servers/
│   └── email_reader/
│       └── server.py                  # MCP server: Gmail IMAP integration
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
| `POST` | `/api/email/sync` | Sync emails → auto-update jobs | ✅ |
| `POST` | `/api/email/preview` | Preview sync (dry run) | ✅ |

### Query Parameters for `GET /api/jobs`

```
?status=interviewing          # Filter by status
?search=google                # Search company/position
?page=1&per_page=10           # Pagination
?sort_by=created_at&order=desc # Sorting
```

---

## 📧 Email Sync — How It Works

The email sync feature uses the **Model Context Protocol (MCP)** to connect your Gmail inbox to the application:

1. **MCP Server** spawns as a subprocess and connects to Gmail via IMAP
2. **Pattern matching** scans email subjects and bodies for job signals:
   - `"schedule.*interview"` → status: **interviewing**
   - `"pleased to offer"` → status: **offer**
   - `"not.*moving forward"` → status: **rejected**
3. **Company extraction** identifies the sender's company from email domain
4. **Job matching** cross-references detected companies with your database
5. **Forward-only updates** ensure statuses only progress forward (never regress)

### Setup Email Sync

1. Enable **2-Step Verification** on your Google account
2. Generate an **App Password** at [myaccount.google.com](https://myaccount.google.com) → Security → App Passwords
3. Add credentials to `.env`:
   ```
   EMAIL_USER=your-email@gmail.com
   EMAIL_PASSWORD=your-16-char-app-password
   ```

---

## 🧪 Testing

```bash
cd backend
pytest tests/ -v
```

```
tests/test_api.py::TestAuth::test_register                    PASSED
tests/test_api.py::TestAuth::test_register_duplicate_email    PASSED
tests/test_api.py::TestAuth::test_login                       PASSED
tests/test_api.py::TestAuth::test_login_wrong_password        PASSED
tests/test_api.py::TestAuth::test_get_me                      PASSED
tests/test_api.py::TestAuth::test_get_me_no_token             PASSED
tests/test_api.py::TestJobs::test_create_job                  PASSED
tests/test_api.py::TestJobs::test_list_jobs                   PASSED
tests/test_api.py::TestJobs::test_filter_by_status            PASSED
tests/test_api.py::TestJobs::test_search_jobs                 PASSED
tests/test_api.py::TestJobs::test_update_job                  PASSED
tests/test_api.py::TestJobs::test_delete_job                  PASSED
tests/test_api.py::TestJobs::test_unauthorized_access         PASSED
```

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
