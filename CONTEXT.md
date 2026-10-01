# PROJECT CONTEXT — AI Career Platform (Project 1)
# =================================================
# This file provides full context for any LLM/developer taking over this project.
# Last updated: 2026-09-28

## PROJECT OVERVIEW
- **Name**: AI Career Platform
- **Purpose**: Job application tracker with email sync and AI-powered features
- **Owner**: tecsmurf (Aditya / Abhi)
- **GitHub**: https://github.com/tecsmurf/Career-Platform.git

## TECH STACK
- **Backend**: FastAPI (Python 3.12), SQLAlchemy 2.0 (async), Pydantic v2
- **Database**: PostgreSQL (Neon serverless, free tier)
- **Frontend**: React 19 + Vite + React Router
- **Auth**: JWT (python-jose) + bcrypt
- **Email Integration**: IMAP over verified TLS (Gmail App Passwords + generic IMAP), provider architecture, review-gated job detection
- **MCP**: Standalone Model Context Protocol server for email reading (not used by the web app)
- **Styling**: Vanilla CSS, dark theme with warm amber/gold accents (#e8a23e)
- **Deployment**: Backend on Render (free), Frontend on Vercel (free), DB on Neon (free)

## ARCHITECTURE
```
React Frontend (Vercel)
     ↓ REST API (axios)
FastAPI Backend (Render)
     ├── /api/auth     → JWT register/login/me
     ├── /api/jobs     → CRUD job applications
     ├── /api/email    → Email integration: status/connect/test/sync/disconnect, messages, suggestions
     └── /api/health   → Health check
     ↓ SQLAlchemy async
PostgreSQL (Neon)
     ├── users (legacy email_* columns deprecated — see Email Integration)
     ├── jobs (company, position, status, salary, location, notes, etc.)
     ├── email_integrations (one active mailbox per user, encrypted credentials)
     ├── email_messages (deduplicated metadata of synced mail)
     └── job_suggestions (extracted jobs awaiting user review)
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
│   │   │   ├── email_sync.py    # /api/email/* (integration, sync, review)
│   │   │   └── health.py        # Health check
│   │   ├── core/encryption.py   # Credential encryption (MultiFernet, owner-bound)
│   │   ├── core/rate_limit.py   # In-process sliding-window limiter
│   │   ├── models/email.py      # EmailIntegration, EmailMessage, JobSuggestion
│   │   ├── schemas/email.py     # Email API request/response models
│   │   └── services/
│   │       ├── auth_service.py      # Password hashing, JWT, user lookup
│   │       ├── job_service.py       # Job CRUD logic
│   │       └── email/               # Email integration package
│   │           ├── providers.py     # EmailProvider → GmailIMAPProvider, GenericIMAPProvider
│   │           ├── network.py       # SSRF guard (resolve once, all-public, IP pinning)
│   │           ├── imap_client.py   # Verified-TLS IMAP transport, read-only, BODY.PEEK
│   │           ├── parsing.py       # Hostile-input MIME parsing, HTML→text
│   │           ├── classifier.py    # Rule-based job-email detection + extraction
│   │           ├── ai_extractor.py  # Optional OpenAI extraction (validated, untrusted-data framing)
│   │           ├── sync.py          # Bounded, idempotent sync engine
│   │           ├── suggestions.py   # Review queue: create/merge/accept/dismiss
│   │           └── integration.py   # Connect/test/disconnect/status
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env (git-ignored)
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # Router setup
│   │   ├── api.js               # Axios instance + API calls
│   │   ├── index.css            # Full design system (dark + amber)
│   │   ├── hooks/useAuth.jsx    # Auth context + token management
│   │   ├── components/email/    # EmailPanel, ConnectEmailModal, SuggestionCard,
│   │   │                        # ReviewSuggestionModal, EmailDetailModal
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
email_host / email_user / email_app_password  -- DEPRECATED legacy columns; no longer
                                  -- read or written (cleared on connect/disconnect)
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

-- email_integrations   (NEW — created automatically by create_all; no ALTER needed)
id, user_id FK→users.id, provider ('gmail'|'imap'), email_address, host, port
encrypted_credentials TEXT        -- Fernet, bound to (user_id, email_address); NULL after disconnect
is_active, status ('connected'|'needs_reconnect'|'disconnected'), status_detail
connected_at, last_verified_at, sync_lock_until, last_sync_started_at, last_sync_at
last_sync_status, last_sync_error, last_sync_scanned/_new_messages/_job_related/_new_suggestions
UNIQUE (user_id, email_address)

-- email_messages       (NEW)
id, user_id, integration_id, message_key (sha256 of Message-ID), provider_message_id,
provider_uid, thread_id, sender_email, sender_name, subject, snippet, body_text (plain text,
job-related only), received_at, is_job_related, category, confidence,
classification_method ('rules'|'ai'), processing_status
UNIQUE (user_id, message_key)     -- idempotent sync

-- job_suggestions      (NEW)
id, user_id, email_id UNIQUE, kind ('new_job'|'status_update'), matched_job_id,
company, position, status, location, salary_min, salary_max, job_url, applied_date,
category, confidence, extraction_method, review_status ('pending'|'accepted'|'dismissed'),
created_job_id, reviewed_at
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
ENVIRONMENT=production          (enables production safety checks)
DATABASE_URL=postgresql+asyncpg://...neon-url...
SECRET_KEY=<openssl rand -hex 32>   (required in production; app refuses to boot otherwise)
EMAIL_ENCRYPTION_KEY=<Fernet key>   (recommended; decouples mailbox creds from SECRET_KEY)
ALLOWED_ORIGINS=https://<your-app>.vercel.app   (recommended; pins CORS)
OPENAI_API_KEY=sk-...           (optional — enables AI extraction; rules work without it)
OPENAI_MODEL=gpt-4o-mini
# EMAIL_HOST / EMAIL_USER / EMAIL_PASSWORD are no longer used (per-user integrations instead)
```

## WHAT'S WORKING ✅
1. User registration with email domain DNS validation (blocks fake domains)
2. User login with JWT tokens
3. Full CRUD for job applications (add, edit, delete, status updates)
4. Dashboard with job stats (applied/interview/offer/rejected counts)
5. Dark theme UI with amber accents
6. Email integration: connect Gmail (App Password) or any IMAP mailbox; verified before saving
7. Email sync: bounded, idempotent, read-only; detects applications, interviews, rejections,
   offers, recruiter outreach; suggestions reviewed by the user before any job changes
8. Optional AI extraction (OpenAI) layered on the rule-based detector
9. MCP email reader server (standalone; hardened: verified TLS, timeout, read-only)
10. Deployed and live on Render + Vercel + Neon (email integration not yet deployed)

## WHAT'S NOT WORKING / DISABLED ⚠️
1. **Live Gmail not exercised end-to-end** — the IMAP path is verified against a real IMAP server
   (pymap) over real verified TLS; Gmail itself needs a manual test with a real App Password.
2. **AI extraction not exercised against the live OpenAI API** — covered with a fake client only.
3. **Sync is synchronous (bounded)** — ≤100 messages, 45 s budget; no background worker yet.
4. **Rate limits for connect/test are in-process** — fine on one Render instance; use a shared
   store if the backend is ever scaled out (sync throttling is DB-based and already safe).
5. **MCP email reader server** — intentionally NOT used by the web app (in-process provider
   layer is simpler and safer); remains a standalone tool.
6. Outlook/Microsoft 365 not supported (Microsoft disabled IMAP basic auth; needs OAuth).

## KNOWN ISSUES & GOTCHAS
- passlib was removed; bcrypt is used directly (`bcrypt==4.2.1`), so the old passlib/bcrypt
  pin issue no longer applies.
- `imaplib.IMAP4_SSL` defaults to an UNVERIFIED TLS context — always pass
  `ssl.create_default_context()` (done in `imap_client.build_tls_context`).
- IMAP `FETCH RFC822`/`BODY[]` marks mail as read — always use `BODY.PEEK` and
  `select(..., readonly=True)`.
- DB drivers (aiosqlite) log SQL parameters at DEBUG — pinned to INFO in connection.py.
- Rotating SECRET_KEY without EMAIL_ENCRYPTION_KEY set makes stored mailbox credentials
  unreadable → users see "Credentials need attention" and must reconnect.
- Neon DATABASE_URL has `?sslmode=require` which asyncpg doesn't accept. 
  The `_fix_database_url()` in connection.py strips it and uses SSL context.
- CORS: exact origins from `ALLOWED_ORIGINS` if set; otherwise falls back to the regex
  `https://.*\.vercel\.app|http://localhost:\d+`
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

### Email Integration & Sync (2026-09-28)
17. Audit found: unverified TLS on every IMAP connection, DNS-rebinding hole in the SSRF check,
    sync marked mail as read and downloaded attachments, subprocess-per-request MCP call with the
    password in env, silent job modification, no dedup, parser crashes on bad charsets.
18. New tables email_integrations / email_messages / job_suggestions (create_all-safe).
19. Provider layer (Gmail + generic IMAP), SSRF guard with IP pinning, verified TLS, timeouts.
20. /api/email/{status,connect,test,sync,disconnect,messages,suggestions} — old
    /api/auth/email-settings and /api/email/preview removed.
21. Idempotent bounded sync with atomic DB lock + cooldown; header-first dedup; only
    job-related emails keep sender/subject/body.
22. Rule-based classifier + optional OpenAI extractor; never fabricates fields; user review
    (edit → accept / ignore) before any job is created or updated.
23. Frontend Email Intelligence panel with all states; axios 401 fix (wrong-password login
    no longer reloads the page); 422 error arrays no longer crash forms.
24. Tests: 138 passing (23 original + 111 email + 4 real-IMAP integration with pymap).
