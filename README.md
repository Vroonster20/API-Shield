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
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

## Running it

You need **two terminals** — the target API and the gateway are separate apps.

**Terminal 1 — fake target API:**
```bash
cd backend
uvicorn target.target_main:app --reload --port 8001
```

**Terminal 2 — gateway:**
```bash
cd backend
uvicorn main:app --reload --port 8000
```

Check both are up:
```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8000/health
```

## Running tests

```bash
cd backend
pytest
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
| **B00** — Project skeleton & config | `main.py`, `core/config.py` | — |
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

Once B08/B09 are implemented, the dashboard will call:

- `POST /admin/login` — returns a session token/cookie
- `GET /admin/logs` — recent request history
- `GET /admin/bans` / `POST /admin/bans` / `DELETE /admin/bans/{id}`
- `GET /admin/settings` / `PUT /admin/settings`
- `POST /admin/fuzz` — runs the fuzz suite, returns pass/fail per case
