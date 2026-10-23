# API-Shield: An API Security Gateway

**Network Security, Fall 2026: Project Report**

**Team:** Justin Vroon, Logan Schmidt, Jim Cha, Joshua Chen

API-Shield is a security gateway that sits between clients and an API. It inspects every request, blocks abusive or malformed traffic, and logs what it sees before anything reaches the protected service. We built it and tested it against a small fake e-commerce API that we wrote for this purpose.

---

## 1. Problem Definition

### 1.1 The problem

APIs are one of the most common attack surfaces on the modern web, because they expose application logic and data directly over HTTP. Typical attacks include:

- **Brute force and credential stuffing**: repeatedly guessing passwords against a login endpoint.
- **Request flooding**: sending large volumes of requests to overload a service or exhaust resources.
- **Malformed and malicious input**: wrong types, missing fields, oversized payloads, or injection strings meant to break parsing or reach the database.
- **Abuse of transactional endpoints**: on an e-commerce API, orders and checkout carry real consequences, so tampering there matters more than on a read-only endpoint.

Many teams, especially small ones, ship APIs without dedicated defenses against these. When authentication and mitigation are poorly implemented, attackers can gain access to the server and a foothold in it.

### 1.2 Why a gateway

Building rate limiting, bans, validation, and logging into every individual API is repetitive and easy to get wrong. A **gateway** solves this by putting a single security layer in front of the API:

- The protected API doesn't need to change.
- All security decisions happen in one place, where they're easy to audit.
- Every request passes through a single point where it can be logged.

### 1.3 Project goals

1. Limit how many requests a client can make in a time window.
2. Ban abusive clients for a configurable duration.
3. Reject malformed input before it reaches the protected API.
4. Log every request, both allowed and blocked, along with the reason.
5. Provide an authenticated admin interface for viewing logs, managing bans, adjusting settings, and running fuzz tests.

### 1.4 Scope

This is a course project, not a product. The pitch is a gateway any site could use, but we deliberately scoped the build to **one gateway protecting one demo target**, so that every team member could understand, implement, and explain each security feature by hand.

| In scope | Deferred (see Section 6) |
|---|---|
| Per-IP rate limiting | Replay attack protection |
| IP bans with expiry | API key security |
| Input validation | Webhook alerts |
| Request logging | Multi-service / multi-tenant support |
| Admin auth and admin API | Production deployment (HTTPS, scaling) |
| Built-in fuzz test runner | |
| Fake e-commerce target API | |

**How the scope changed.** Our original proposal targeted a single secured API using MySQL. We first broadened it into a reusable gateway, and a teammate drafted an extensive production-grade specification for that version. After reviewing it as a group, we concluded it was beyond what four students could build, understand, and verify in a semester, so we narrowed it to the scope above. We also replaced MySQL with SQLite, because a local single-file database removes setup overhead and fits a single-gateway demo.

---

## 2. Architecture

```
Client ──► API-Shield Gateway (port 8000) ──► Fake Target API (port 8001)
                    │                                   │
               shield.db                            target.db
          (logs, bans, settings)                 (users, orders)

Admin Dashboard (frontend/) ──► Gateway's /admin/* routes
```

- **Gateway** (`backend/`): a FastAPI app that receives client requests, applies the security checks, and forwards approved requests to the target.
- **Fake target API** (`backend/target/`): a separate FastAPI app with its own database. It behaves like a small store and has no knowledge of the gateway.
- **Admin dashboard** (`frontend/`): a web UI that calls the gateway's authenticated `/admin/*` endpoints.

The two apps run as separate processes with separate databases, as they would in a real deployment.

### 2.1 Request pipeline

Every request to a protected route goes through these checks in order. The first failure stops the request.

1. **Ban check**: if the client IP is currently banned, return `403`.
2. **Rate limit**: if the IP is over its limit, return `429`.
3. **Input validation**: if the body doesn't match the expected schema, return `422`.
4. **Logging**: record the outcome (allowed or blocked) and the reason.
5. **Forwarding**: send the approved request to the target API and relay its response.

Bans are checked before rate limits, so a banned client is rejected cheaply without touching the counters.

### 2.2 Technology stack

| Layer | Choice | Reason |
|---|---|---|
| Gateway and target | Python, FastAPI | Built-in request validation through Pydantic and good testing support |
| Database | SQLite (Python `sqlite3`) | No server to install, transparent raw SQL, sufficient for one gateway |
| HTTP forwarding | `httpx` | Async-capable HTTP client for forwarding requests |
| Testing | `pytest`, FastAPI `TestClient` | Tests run in-process without starting servers |
| Frontend | TypeScript | A TypeScript web interface with pages for login, logs, bans, settings, and fuzzing |

---

## 3. Work Done

Development was split into ten backend tasks (B00 to B09) and one frontend task (F00). Each task owned specific files and had a test file that defined what "done" meant. Owners are listed in Section 7.

### 3.1 Project skeleton and configuration (B00)

A FastAPI app loads its settings (rate limit, ban duration, database path, target URL, admin credentials) from a `.env` file through `pydantic-settings`. A `/health` endpoint confirms the app is running.

### 3.2 Database layer (B01)

A small layer built on plain `sqlite3`, with three tables:

- `requests_log`: timestamp, IP, path, decision, and reason for each request.
- `bans`: IP, ban start time, and expiry time.
- `rules`: runtime-editable settings.

All SQL lives in helper functions (`insert_log`, `insert_ban`, `get_active_ban`, `get_recent_logs`), so other modules never write raw SQL. Every query uses **parameterized placeholders** (`?`), which keeps user-supplied values such as IPs and paths from being interpreted as SQL. This prevents SQL injection in the gateway's own database. Timestamps are stored as UTC ISO-8601 strings, which sort chronologically when compared as text.

### 3.3 Fake target API (B02)

A standalone FastAPI app that simulates a small store, with endpoints for login, get_orders, place_order, payment and its own `target.db` containing users and orders. It is not a real store. It exists to give the gateway realistic, state-changing endpoints to protect.

### 3.4 Rate limiter (B03)

We implemented a **sliding-window log** rate limiter. For each IP, the limiter stores the timestamps of its recent allowed requests. On each new request it:

1. Discards timestamps older than the window.
2. Allows the request and records its timestamp if fewer than the limit remain.
3. Denies the request otherwise.

Design decisions:

- **Sliding window instead of fixed window.** A fixed-window limiter allows a burst of up to twice the limit at a window boundary (the limit at the end of one window, then again at the start of the next). The sliding log avoids that.
- **Denied requests are not recorded**, so a blocked client's retries don't extend its own block.
- **Settings are read on every call**, so changing the limit through the admin API takes effect immediately.
- State is kept in memory, which is enough for a single-process demo. It resets when the server restarts.

### 3.5 Ban manager (B04)

`ban_ip(ip)` bans an IP for `settings.ban_duration_seconds`, and `is_banned(ip)` checks whether it has an unexpired ban. Bans are stored in SQLite, so they survive restarts, and they stop applying once `expires_at` passes, with no cleanup job needed. Timestamps always use the same UTC format, which keeps the expiry comparison reliable.
** Bans are stored in the `bans` table, and a ban is active while its `expires_at` time is in the future, so expired bans stop applying with no cleanup job.

### 3.6 Input validation (B05)

Pydantic models define the expected field names and types for each protected request body: `LoginAttempt` (username and password), `Order` and `CustomerOrderRequest` (order data), and `PaymentBody` (a payment event with nested `PaymentDetails` and `PaymentRequest` objects). Requests with missing fields or wrong types are rejected with `422` at the gateway and never reach the target API.

### 3.7 Logging (B06)

`log_event(ip, path, decision, reason)` writes one row to `requests_log` for every request the gateway handles, whether it was allowed or blocked. The reason field records why a request was blocked (for example `banned`, `rate_limit`, or `invalid_input`).

### 3.8 Gateway routes (B07)

The integration point. Each protected route mirrors a target endpoint and runs the pipeline from Section 2.1, forwarding approved requests to the target with `httpx`.

Protected routes:
- `POST /gateway/login`
- `GET /gateway/orders`
- `POST /gateway/db/orders`
- `POST /gateway/webhooks/payments`

Gateway operations:
- **Validates IP address and request body.** Checks if IP has been ratelimited or banned and validates request
body against Pydantic Models.
- **Appends signature to header.** Adds HMAC signature to header so that the target API knows that the request
has been through the gateway. The target API will reject any request without the signature.
- **Forwards request to target API.** Request is forwarded to target API using httpx.
- **Returns response from target API.** Response from target API is returned to the user

### 3.9 Admin authentication (B08)

The admin API is protected by token-based authentication:

- `POST /admin/login` accepts the username and password **in the request body**, never in the URL, so credentials don't appear in server logs or browser history.
- Credentials are compared with `secrets.compare_digest`, a constant-time comparison that prevents timing attacks from revealing how much of a guess was correct.
- A wrong username and a wrong password return the **same** error, so an attacker can't learn which one was right.
- A successful login returns a random 256-bit token from Python's `secrets` module. Clients send it as `Authorization: Bearer <token>`.
- Tokens expire after 1 hr. Missing, invalid, and expired tokens all return `401`.

Sessions are kept in memory, so all admins are logged out when the server restarts.

### 3.10 Admin API and fuzz runner (B09)

Authenticated endpoints let the dashboard view logs, list, create, and revoke bans, read and update settings, and run the fuzz suite (full list in Appendix B).

The **fuzz runner** sends a fixed set of malformed and boundary-case requests through the gateway and checks that each one gets the expected response. A case passes when the gateway behaves correctly, which usually means rejecting the bad request. Valid control requests check that legitimate traffic still gets through. The fuzzer sends payloads that have incorrect method, bad request data, and endpoints that don't exist

### 3.11 Admin dashboard (F00)

A TypeScript web interface with pages for login, logs, bans, settings, and fuzzing.

---

## 4. Testing

### 4.1 Method

- Each backend task has a matching test file in `backend/tests/` that defines when the task is done.
- Tests use FastAPI's `TestClient`, which runs the app in-process, so no servers need to be running.
- Time-dependent behavior (rate-limit windows, token expiry) is tested by **patching `time.time`**, so tests can simulate minutes passing without waiting.
- Database tests use a temporary database, so they never touch real data.
- Shared in-memory state (rate-limit counters, sessions) is cleared between tests, so they don't affect each other.

### 4.2 Test coverage by component

| Component | Test file | What the tests verify |
|---|---|---|
| Skeleton | `test_health.py` | App boots, `/health` returns 200 |
| Database | `test_database.py` | Tables are created; bans become inactive after expiry; logs round-trip |
| Rate limiter | `test_rate_limit.py` | Requests up to the limit pass; the next is denied; the window resets; after a reset the limit is enforced again; IPs are counted independently |
| Ban manager | `test_bans.py` | IPs start unbanned; bans block only the banned IP; bans last the configured duration and expire on time |
| Validation | `test_validation.py` | Valid payment payloads pass; order payloads with a missing field or a wrong type are rejected |
| Gateway | `test_gateway.py` | Banned IPs are blocked; Ratelimited IP's are logged and blocked; Allowed requests recieve a response |
| Admin auth | `test_auth.py` | Correct login returns a token; wrong credentials return 401; wrong username and wrong password give identical responses; missing and invalid tokens return 401; a valid token reaches protected routes; tokens are valid just before expiry and rejected after |
| Admin API and fuzzing | **[FILL IN]** | **[FILL IN]** |

---

## 5. Results

### 5.1 Automated tests

**[FILL IN: total count, e.g. "All N tests pass" from running `python -m pytest`. Include a screenshot of the output if your instructor wants evidence.]**

### 5.2 Feature demonstrations

**[FILL IN the "Observed" column from your actual demo runs.]**

| Scenario | Expected | Observed |
|---|---|---|
| Valid order request through the gateway | Forwarded; target's `200` response returned; logged as `allowed` | |
| Request N+1 from one IP inside the window | `429`; logged as `rate_limit` | |
| Same IP after the window passes | Allowed again | |
| Request from a banned IP | `403` before the rate limit is checked; logged as `banned` | |
| Banned IP after the ban expires | Allowed again | |
| Malformed body (missing field or wrong type) | `422`; never reaches the target | |
| Admin route with no token | `401` | |
| Admin route after login | `200` | |

### 5.3 Fuzz testing

**[FILL IN: a table of fuzz cases with their expected and actual status codes, plus a short summary such as "X of Y cases passed." If any case failed, say what it revealed and how you fixed it. A real finding is stronger evidence than a perfect score.]**

### 5.4 Summary

**[FILL IN: 2–3 sentences on how well the gateway met each goal from Section 1.3.]**

---

## 6. Limitations and Future Work

### 6.1 Known limitations

- **State resets on restart.** Rate-limit counters and admin sessions are kept in memory, so restarting the gateway clears them. Bans and logs survive because they're stored in SQLite.
- **Shared IPs.** Users behind the same NAT or proxy share one IP, so they share a rate limit and a ban.
- **Single process.** The design assumes one gateway process. Multiple instances would need shared state, for example Redis.
- **Demo-grade admin auth.** There is one admin account with no password hashing. That's acceptable for a local demo, but it would need a proper user store before any real deployment.
- **The target enforces its own business rules.** The gateway checks the shape of a request, not whether a user owns the order they're modifying. Authorization stays in the protected API.
- **No HTTPS.** Everything runs locally over HTTP, so a real deployment would need TLS at the edge.
- **Vulnerable to replay attacks** - no timestamps are attached to the gateway signatures so attackers could intercept and rerun requests with valid signatures

### 6.2 Future work

- Replay attack protection (signed requests with timestamps and nonces).
- Per-route security policies, such as stricter limits on `/login` than on `/orders`.
- API key support for client identification.
- Webhook alerts on bans and repeated violations.
- Docker Compose to start the full stack with one command.

---

## 7. Team Contributions

| Member | Tasks |
|---|---|
| Justin Vroon | B00 (skeleton), B01 (database), B03 (rate limiter), B08 (admin auth) |
| Logan Schmidt | B02 (fake target API), B05 (input validation), B07 (gateway routes), testing gateway |
| Jim Cha | B04 (ban manager), B09 (admin API), updated database layer |
| Joshua Chen | F00 (frontend),  |

---

## Appendix A: Setup and Running

**Requirements:** Python 3.11+

```bash
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
copy .env.example .env              # macOS/Linux: cp .env.example .env
```

Run all commands from `backend/`. Start each app in its own terminal:

```bash
# Terminal 1: fake target API
python -m uvicorn target.target_main:app --reload --port 8001

# Terminal 2: gateway
python -m uvicorn main:app --reload --port 8000
```

Check that both are running:

```bash
curl.exe http://127.0.0.1:8001/health     # macOS/Linux: curl
curl.exe http://127.0.0.1:8000/health
```

Run the tests (no servers needed):

```bash
python -m pytest
```

**[FILL IN: steps to run the frontend.]**

## Appendix B: Admin API

All routes except login require an `Authorization: Bearer <token>` header.

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/admin/login` | Body `{username, password}`; returns `{access_token, token_type}` |
| `GET` | `/admin/logs` | Recent request history |
| `GET` | `/admin/bans` | List bans |
| `POST` | `/admin/bans` | Ban an IP |
| `DELETE` | `/admin/bans/{id}` | Revoke a ban |
| `GET` | `/admin/settings` | Current rate-limit and ban settings |
| `PUT` | `/admin/settings` | Update settings |
| `POST` | `/admin/fuzz` | Run the fuzz suite; returns pass/fail per case |

## Appendix C: Project Structure

```
backend/
├── main.py                  # gateway entry point
├── requirements.txt
├── .env.example
├── app/
│   ├── core/config.py       # settings loaded from .env
│   ├── db/database.py       # sqlite3 connection, tables, query helpers
│   ├── security/
│   │   ├── rate_limiter.py  # sliding-window rate limiting
│   │   ├── ban_manager.py   # IP bans with expiry
│   │   └── validator.py     # Pydantic request models
│   ├── logging/logger.py    # request logging
│   ├── routes/
│   │   ├── gateway.py       # protected endpoints
│   │   ├── auth.py          # admin login and token checks
│   │   └── admin.py         # admin API
│   └── fuzzing/fuzz_runner.py
├── target/                  # fake target API
│   ├── target_main.py
│   └── target_db.py
└── tests/
frontend/                    # admin dashboard
```
