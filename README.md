# API-Shield

A security gateway that sits in front of an API and applies rate limiting,
IP bans, and input validation before forwarding requests through — tested
against a small fake target API built for this project.

This is a scoped-down, hand-written version of the original idea: one
gateway protecting one demo target, not a general-purpose product. The
goal is to actually understand and implement the five security features,
not to build production infrastructure.

## Architecture

```
Client --> Gateway (backend/)  --> Target API (backend/target/)
              |                         |
          shield.db                 target.db
       (logs, bans, rules)       (users, orders)

Admin dashboard (frontend/, built later) --> Gateway's /admin/* routes
```

The gateway and the target API are two separate FastAPI apps, each with
its own SQLite database, running on different ports. The gateway doesn't
know or care about the target's internals — it just forwards approved
requests and relays the response.

## Setup

**Requirements:** Python 3.11+

```bash
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1      #Linux: source .venv/bin/activate      
pip install -r requirements.txt
cp .env.example .env
```

## Running it

You need **two terminals** — the target API and the gateway are separate apps.

**Terminal 1 — fake target API:**
```bash
cd backend
python main.py
```

**Terminal 2 — gateway:**
```bash
cd backend/target
python target_main.py
```

Check both are up:
```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8000/health
```

## Running tests

```bash
cd backend
python -m pytest
```

## Project structure

```
backend/
├── main.py                  # gateway entry point
├── requirements.txt
├── .env.example
├── app/
│   ├── core/config.py       # settings loaded from .env
│   ├── db/database.py       # sqlite3 connection + table creation
│   ├── security/
│   │   ├── rate_limiter.py  # per-IP request counting
│   │   ├── ban_manager.py   # check/add bans
│   │   └── validator.py     # Pydantic request models
│   ├── logging/logger.py    # writes to requests_log
│   ├── routes/
│   │   ├── gateway.py       # the protected endpoints
│   │   ├── auth.py          # admin login
│   │   └── admin.py         # dashboard API (logs, bans, settings, fuzz)
│   └── fuzzing/fuzz_runner.py
├── target/                  # the fake app being protected
│   ├── target_main.py
│   └── target_db.py
└── tests/                   # one test file per task below
frontend/                    # not built yet — see frontend/README.md
```

## Task breakdown

Each file above has a `[Task Bxx]` docstring pointing back to this list.
Check a task's corresponding test file in `backend/tests/` to see what
"done" means for it.

| Task | Owns | Depends on |
|---|---|---|
| **B00** — Project skeleton & config | `main.py`, `backend/app/core/config.py` | — |
| **B01** — Database layer | `db/database.py` | B00 |
| **B02** — Fake target API | `target/` | — (independent, good first task) |
| **B03** — Rate limiter | `security/rate_limiter.py` | B01 |
| **B04** — Ban manager | `security/ban_manager.py` | B01 |
| **B05** — Input validation | `security/validator.py` | B02 |
| **B06** — Logging | `logging/logger.py` | B01 (already implemented — see note below) |
| **B07** — Gateway routes | `routes/gateway.py` | B02–B06 |
| **B08** — Admin auth | `routes/auth.py` | B01 |
| **B09** — Admin API + fuzzing | `routes/admin.py`, `fuzzing/fuzz_runner.py` | B07, B08 |

**Note:** `logging/logger.py` (B06) is already fully implemented as a
reference example of what "done" looks like for a small, self-contained
module — the rest of `security/` and `routes/` are stubs with `TODO`
comments and `NotImplementedError` for the group to fill in.

**Suggested 4-person split:** one person on B00/B01, one on B02 (fully
independent — good to start immediately), one on B03/B04, one on B05 —
then B07 (integration) goes to whoever finishes first, and B08/B09 split
between the remaining two.

## Frontend task

| Task | Owns | Depends on |
|---|---|---|
| **F00** — Frontend (AI-generated) | `frontend/` | B08, B09 (must be functionally complete, not just stubbed) |

### F00 — Frontend (AI-generated)

**Depends on:** B08 (admin auth) and B09 (admin API) being functionally
complete — not just stubbed out.

Generate the dashboard against the **actual, working** `/admin/*`
endpoints (login, logs, bans, settings, fuzz) — not a guessed or assumed
API shape. Don't start this task until B08/B09 can be tested with
curl/Postman and return real data.

**Why the dependency matters:** generating the frontend before the admin
endpoints are solid means the AI will invent field names and assumptions
about what a "ban" or "log" object looks like. Fixing that mismatch later
costs more time than just waiting for the real contract to exist first.

**Done when:**
- Login, Logs, Bans, Settings, and Fuzzing pages all call the real
  `/admin/*` endpoints — no mock/placeholder data left in.
- Someone can log in, view real log rows, ban/revoke a real IP, and
  trigger a real fuzz run, entirely through the UI.
- Whoever owns this task can explain what the generated code does and
  why — not just paste it in unreviewed.

## Admin API contract (for the future frontend)

The dashboard can call:

- `POST /admin/login` — returns a session token/cookie
- `GET /admin/logs` — recent request history
- `GET /admin/bans` / `POST /admin/bans` / `DELETE /admin/bans/{id}`
- `GET /admin/settings` / `PUT /admin/settings`
- `POST /admin/fuzz` — runs the fuzz suite, returns pass/fail per case

### B09 usage

All routes above except login require `Authorization: Bearer <access_token>`.
Use the token returned by `POST /admin/login`.

- Logs return `{"logs": [...]}`. Optional `?limit=50` accepts 1–500 rows, newest first.
- Bans return `{"bans": [...]}` with active rows and their IDs. Create one with
  `{"ip": "192.0.2.1"}`. Delete by ID; success returns 204, a missing ID returns 404.
- Settings GET and PUT use the same three fields. PUT requires all three:

```json
{
  "rate_limit_requests": 10,
  "rate_limit_window_seconds": 60,
  "ban_duration_seconds": 300
}
```

Values must be integers from 1 to 10000, 86400, and 604800 respectively.
Settings are saved in the `rules` table and restored on startup. They apply to
the running process; existing bans keep their original expiration times.
The demo uses one gateway process, so run without multiple workers.

Fuzzing runs ten fixed cases against `http://127.0.0.1:8000`, never the target
directly. Start the gateway on port 8000 and the target on port 8001.
The response contains `results`, `passed`, and `total`; each case contains
`name`, `expected`, `actual`, and `passed`. Connection errors include `error`
and use `actual: null`. Each request has a five-second timeout.

The cases cover health, login validation, invalid JSON, missing order/payment
fields, and a login with valid fields but incorrect credentials. Login cases
use the current gateway's GET route; change them if B07 switches to POST.
The health case only checks availability. The login control expects 401 from
the target, not a successful sign-in. Existing bans and rate counters affect
the run, and 403, 429, or 500 responses do not count as passing validation.
The runner does not clear protection state. B07's existing routing, rate-limit,
and validation bugs can therefore produce failed cases.

Run the B09 tests from `backend/`:

```bash
python -m pytest tests/test_admin.py tests/test_fuzz.py
```

These tests use temporary databases and mocked HTTP responses for the fuzz
runner. They do not require a running target or modify the demo database.
