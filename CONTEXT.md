# PROJECT CONTEXT — AI Career Platform (Project 1)
# =================================================
# This file provides full context for any LLM/developer taking over this project.
# Last updated: 2026-09-27

## PROJECT OVERVIEW
- **Name**: AI Career Platform
- **Purpose**: Job application tracker with email sync and AI-powered features
- **Owner**: tecsmurf (Aditya / Abhi)
- **GitHub**: https://github.com/tecsmurf/Career-Platform.git

## TECH STACK
- **Backend**: FastAPI (Python 3.12), SQLAlchemy 2.0 (async), Pydantic v2
- **Database**: PostgreSQL (Neon serverless, free tier)
- **Frontend**: React 19 + Vite + React Router
- **Auth**: JWT (python-jose) + bcrypt (passlib)
- **Email Sync**: IMAP (Gmail App Passwords) — per-user config
- **MCP**: Model Context Protocol server for email reading
- **Styling**: Vanilla CSS, dark theme with warm amber/gold accents (#e8a23e)
- **Deployment**: Backend on Render (free), Frontend on Vercel (free), DB on Neon (free)

## ARCHITECTURE
```
React Frontend (Vercel)
     ↓ REST API (axios)
FastAPI Backend (Render)
     ├── /api/auth     → JWT register/login/me
     ├── /api/jobs     → CRUD job applications
     ├── /api/email    → Email sync (CURRENTLY DISABLED - "Coming Soon")
     └── /api/health   → Health check
     ↓ SQLAlchemy async
PostgreSQL (Neon)
     ├── users (with email_host, email_user, email_app_password)
     └── jobs (company, position, status, salary, location, notes, etc.)
```

## FILE STRUCTURE
```
PROJECT_1_CAREER_PLATFORM/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, lifespan, CORS
│   │   ├── core/config.py       # Settings (env vars)
│   │   ├── database/connection.py  # Async engine, session, init_db
│   │   ├── models/models.py     # User, Job ORM models
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── api/
│   │   │   ├── __init__.py      # Router aggregation
│   │   │   ├── auth.py          # Register, login, /me endpoints
│   │   │   ├── jobs.py          # CRUD for job applications
│   │   │   ├── email_sync.py    # Email settings + sync (DISABLED in UI)
│   │   │   └── health.py        # Health check
│   │   └── services/
│   │       ├── auth_service.py      # Password hashing, JWT, user lookup
│   │       ├── job_service.py       # Job CRUD logic
│   │       └── email_sync_service.py # IMAP connection, email parsing
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env (git-ignored)
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # Router setup
│   │   ├── api.js               # Axios instance + API calls
│   │   ├── index.css            # Full design system (dark + amber)
│   │   ├── hooks/useAuth.jsx    # Auth context + token management
│   │   └── pages/
│   │       ├── LoginPage.jsx
│   │       ├── RegisterPage.jsx
│   │       └── DashboardPage.jsx  # Main app (job list, add job, stats)
│   ├── package.json
│   └── vite.config.js
├── mcp_servers/
│   └── email_reader/server.py   # MCP server for IMAP email reading
├── Dockerfile                    # Root Dockerfile for Render
├── docker-compose.yml
└── README.md
```

## DATABASE SCHEMA
```sql
-- users
id SERIAL PRIMARY KEY
email VARCHAR(255) UNIQUE NOT NULL
full_name VARCHAR(255) NOT NULL
hashed_password VARCHAR(255) NOT NULL
is_active BOOLEAN DEFAULT true
email_host VARCHAR(255) DEFAULT 'imap.gmail.com'
email_user VARCHAR(255)           -- per-user Gmail address
email_app_password VARCHAR(255)   -- encrypted with Fernet
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ

-- jobs
id SERIAL PRIMARY KEY
user_id INTEGER FK→users.id
company VARCHAR(255) NOT NULL
position VARCHAR(255) NOT NULL
status VARCHAR(50) DEFAULT 'applied'  -- applied/interview/offer/rejected/saved
job_url VARCHAR(500)
salary_min INTEGER
salary_max INTEGER
location VARCHAR(255)
notes TEXT
applied_date DATE
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

## DEPLOYMENT STATUS
| Component | Status | URL |
|-----------|--------|-----|
| GitHub | ✅ Deployed | https://github.com/tecsmurf/Career-Platform |
| Backend (Render) | ✅ Deployed | https://career-platform-api.onrender.com |
| Frontend (Vercel) | ✅ Deployed | (check Vercel dashboard) |
| Database (Neon) | ✅ Connected | (via DATABASE_URL env var) |

## ENV VARS NEEDED (on Render)
```
DATABASE_URL=postgresql+asyncpg://...neon-url...
SECRET_KEY=random-64-char-string
EMAIL_HOST=imap.gmail.com       (default, users override per-account)
OPENAI_API_KEY=sk-...           (for AI features — currently unused in MVP)
OPENAI_MODEL=gpt-4o-mini
```

## WHAT'S WORKING ✅
1. User registration with email domain DNS validation (blocks fake domains)
2. User login with JWT tokens
3. Full CRUD for job applications (add, edit, delete, status updates)
4. Dashboard with job stats (applied/interview/offer/rejected counts)
5. Dark theme UI with amber accents
6. Per-user email settings (IMAP host, user, app password) — stored encrypted
7. IMAP connection validation before saving settings
8. MCP email reader server (standalone)
9. Deployed and live on Render + Vercel + Neon

## WHAT'S NOT WORKING / DISABLED ⚠️
1. **Email Sync UI** — Disabled, shows "Coming Soon"
   - Backend endpoints exist and work (`/api/email/settings`, `/api/email/sync`)
   - Frontend has the UI but it's hidden behind a "Coming Soon" overlay
   - Issue: Email sync was accepting wrong app passwords (was fixed with IMAP validation)
   - Decision: Disabled in UI until the full feature is polished
2. **AI-powered job matching from emails** — Not implemented yet
   - The email_sync_service has parsing logic but AI categorization is TODO
3. **MCP email reader server** — Built but not integrated into the main app

## KNOWN ISSUES & GOTCHAS
- `passlib==1.7.4` + `bcrypt>=4.1` is broken. Pin `bcrypt==4.0.1`
- Neon DATABASE_URL has `?sslmode=require` which asyncpg doesn't accept. 
  The `_fix_database_url()` in connection.py strips it and uses SSL context.
- CORS uses regex: `https://.*\.vercel\.app|http://localhost:\d+`
- Free Render tier spins down after 15min idle (cold start ~30s)

## DESIGN RULES
- ❌ NO blue, purple, indigo, or violet colors anywhere
- ✅ Dark theme: #0f0f0f background, #1a1a1a cards, #2a2a2a borders
- ✅ Accent: #e8a23e (warm amber/gold)
- ✅ Font: Inter (Google Fonts)

## RECENT COMMIT HISTORY (newest first)
```
d818c94 ui: disable email sync - show Coming Soon
59451a6 fix: verify IMAP connection before saving email settings
c34be95 security: block registration with fake email domains
a01e7cb security: encrypt email app passwords with Fernet
95e6c71 feat: per-user email settings
de97088 fix: MCP SDK v1.29 compatibility
478df67 fix: CORS regex for Vercel
a19de77 initial commit (deployed)
```

## ERROR HISTORY & TROUBLESHOOTING LOG
### These are all errors encountered during development, with solutions.

### Error 1: Email App Password Accepted Wrong Credentials
- **When**: During email sync feature development
- **Problem**: User entered wrong Gmail app password but system accepted it and "connected"
- **Root Cause**: No IMAP connection validation — code just saved the password without testing
- **Fix**: Added IMAP connection test in email settings endpoint — tries actual IMAP login before saving
- **Commit**: 59451a6 fix: verify IMAP connection before saving email settings
- **Status**: Fixed, but entire email sync UI is disabled ("Coming Soon") pending polish

### Error 2: Fake Email Domains Accepted During Registration
- **When**: During registration security review
- **Problem**: Users could register with non-existent email domains (e.g., user@asdfgh.com)
- **Fix**: Added DNS MX record check — validates that the email domain has mail servers
- **Commit**: c34be95 security: block registration with fake email domains using DNS MX check
- **Status**: FIXED

### Error 3: Email Sync Feature Not Production-Ready
- **When**: After deployment
- **Problem**: Email sync had multiple issues (wrong password acceptance, no validation)
- **Decision**: Disabled email sync UI — shows "Coming Soon" overlay
- **Commit**: d818c94 ui: disable email sync - show Coming Soon
- **Status**: DISABLED — backend endpoints still exist, UI is hidden
- **To Resume**: Remove the "Coming Soon" overlay in DashboardPage.jsx, fix remaining issues

### Error 4: MCP SDK v1.29 Compatibility
- **When**: During MCP server integration
- **Problem**: MCP SDK updated to v1.29, changed InitializationOptions API
- **Fix**: Used server.create_initialization_options() instead of manual init
- **Commits**: de97088,  bd148f
- **Status**: FIXED

### Error 5: Neon Database SSL Incompatibility
- **When**: First deployment to Render with Neon DB
- **Problem**: Neon URLs include ?sslmode=require&channel_binding=require which asyncpg rejects
- **Fix**: Created _fix_database_url() function that strips query params and creates SSL context
- **Commit**: 126df4e fix: strip ALL query params from Neon URL for asyncpg compatibility
- **Status**: FIXED — function exists in database/connection.py, shared pattern with Project 2

### Error 6: Leaked Neon Credentials in docker-compose
- **When**: Early commits
- **Problem**: Neon connection string was hardcoded in docker-compose.yml
- **Fix**: Removed credentials, uses env vars instead
- **Commit**: 8516e2e security: remove leaked Neon credentials and secret key
- **Status**: FIXED

## NOTABLE CHANGES (made independently by the developer, not yet committed)

### Backend Security Hardening
1. Production-safe config - ENVIRONMENT toggle, enforces strong SECRET_KEY in prod
2. SSRF protection - _host_is_public() blocks private/loopback IPs in email host
3. Direct bcrypt - Dropped passlib, uses bcrypt==4.2.1 directly (no more version hell)
4. JobStatus enum - Backend validates status values, salary_max >= salary_min
5. Deactivated user check - Tokens for inactive accounts are rejected
6. Async DNS validation - Email domain check runs off event loop, fails open on DNS errors
7. Error message hardening - No internal connection details leaked to client

### Frontend Complete Overhaul
8. 7 new components: AuthShell, Modal (accessible w/ focus trap), ConfirmDialog, Pipeline (visual funnel), Skeleton, StatusBadge, icons.jsx (25 custom SVGs)
9. Toast notification system - ToastProvider + useToast() replaces console.error/alert
10. Constants system - Single source of truth for statuses, colors, pipeline order
11. Design system tokens - Full CSS variable system (surfaces, text, accent, status, feedback)
12. Dashboard rewrite - Debounced search, pipeline viz, skeleton loading, confirm dialogs
13. Auth pages - Split-pane layout with brand panel + feature highlights
14. Router fixes - replace on Navigate, FullLoader spinner
15. Test infrastructure - New conftest.py, updated test_api.py
16. Vercel config - vercel.json for SPA routing

### Impact: 18 modified files + 12 new files | 1187 insertions, 782 deletions
### Status: UNCOMMITTED - needs git add && git commit && git push
