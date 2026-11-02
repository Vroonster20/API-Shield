# API-Shield v2: Task Breakdown

Project 2 has two parts:

- **Part A (S00–S06):** fix the security problems in the Project 1 code.
- **Part B (P00–P07):** add new features that answer the question *"is this request authentic and authorized?"*

Each task lists the files it owns, what it depends on, and when it's done. Every task should end with tests that prove the fix or feature works.

**Before starting:** tag the submitted Project 1 code so the attack suite (P07) can run against it later:

```bash
git tag v1.0 <commit-you-turned-in>
git push origin v1.0
```

---

## Part A: Fix the current security problems

| Task | Fixes | Owns | Depends on |
|---|---|---|---|
| **S00** — Secret handling | Empty signing key | `core/config.py`, new `app/security/signing.py`, `.env.example` | — |
| **S01** — Gateway forwarding | Copy-pasted forwarding, unsigned GET, hardcoded URLs | `routes/gateway.py` | S00 |
| **S02** — Target signature checks | Gateway bypass | `target/target_main.py` | S00 |
| **S03** — Gateway pipeline and logging | Wrong check order, wrong logs, time zones | `routes/gateway.py`, `logging/logger.py`, `routes/admin.py` | S01 |
| **S04** — Target login fixes | Password printing, crash on unknown user | `target/target_main.py`, `target/target_db.py` | — |
| **S05** — Admin credential fixes | Plaintext compare, default password | `routes/auth.py`, `core/config.py` | — |
| **S06** — Tests and dependencies | Failing test, stale dependencies, warnings | `tests/`, `requirements.txt` | — |

### S00 — Secret handling

The gateway and target load `SHARED_SECRET_KEY` from `.env.example`, which holds an empty value, so every signature is computed with an empty key and can be forged.

- Load the key through `settings` (from `.env`) in both apps. Never read `.env.example` at runtime.
- Remove the duplicate `shared_secret_key` field in `config.py`.
- Refuse to start if the key is missing, empty, not valid hex, or shorter than 32 bytes.
- Put the signing and verification code in one module, `app/security/signing.py`, used by both apps, so the format can't drift between them.
- `.env.example` gets a placeholder and the command to generate a key.

**Done when:** both apps refuse to start without a valid key, and a test shows a signature made with the wrong key is rejected.

### S01 — Gateway forwarding

The four gateway routes each contain a copy of the forwarding code, URLs are hardcoded to `127.0.0.1:8001`, and `GET /orders` is forwarded with no signature.

- Write one `forward(request, path, body)` helper used by every route.
- Build target URLs from `settings.target_api_url`.
- Sign **every** forwarded request, including GETs. The signature should cover the method and path as well as the body, so a signature can't be moved to a different route.
- Set a timeout. If the target is down, return `502` and log it instead of crashing.

**Done when:** every route uses the helper, and tests confirm each forwarded request carries a valid signature.

### S02 — Target signature checks

The target listens on port 8001 and accepts direct connections. `GET /orders/{customer_id}` doesn't check signatures at all, so clients can skip the gateway.

- Check the signature on **every** target route, using the shared helper from S00.
- Return `403` (not `400`) for missing or invalid signatures.
- Bind the target to `127.0.0.1` only.

**Done when:** a request sent straight to the target without a valid signature is rejected on every route.

### S03 — Gateway pipeline and logging

Each route declares its body model as a parameter, so FastAPI rejects bad bodies with `422` **before** the handler runs. The ban check and rate limit never see those requests, and they're never logged. Some routes also log `allowed` before validating, the webhook route logs its path as `/orders`, and the reason `rate-limited` doesn't match the `rate_limit` used elsewhere.

- Read the raw body and run the checks in the documented order: ban, rate limit, validation, log, forward.
- Log every rejected request, including validation failures as `blocked` / `invalid_input`.
- Log exactly once per request, with the correct path and consistent reason codes.
- Use UTC everywhere. `logger.py` and `GET /admin/bans` currently use local time, so the dashboard shows expired bans as active for hours.

**Done when:** tests show a malformed request from a banned IP gets `403` (not `422`), each request produces one log row, and the logged path and reason are correct.

### S04 — Target login fixes

- Remove the `print` statements, which write submitted passwords to the console.
- Unknown usernames should return `401`, not crash with `500`.
- Missing username or password returns `401` or `422`, not an unhandled `ValueError`.

**Done when:** tests cover an unknown user, a missing field, and a wrong password, and none produce a `500` or print credentials.

### S05 — Admin credential fixes

- Compare the admin username and password with `secrets.compare_digest`.
- Refuse to start if `ADMIN_PASSWORD` is still `changeme`.

**Done when:** tests confirm wrong credentials still return identical `401` responses, and the app refuses the default password.

### S06 — Tests and dependencies

- Fix `test_gateway.py`, which fails unless a `shield.db` already exists. Add a fixture that creates tables in a temporary database.
- Remove `pandas` from `requirements.txt` and merge the `csv` fix for `target_db.py`.
- Clear the deprecation warnings (`class Config` → `model_config`; pass timestamps to SQLite as ISO strings).

**Done when:** `python -m pytest` passes on a fresh clone with no `shield.db`.

---

## Part B: New features

| Task | Feature | Owns | Depends on |
|---|---|---|---|
| **P00** — Replay protection | Timestamp + nonce on signed requests | `security/signing.py`, target nonce store | S00–S02 |
| **P01** — User authentication | Real login and expiring tokens at the target | `target/` | S04 |
| **P02** — Gateway token checks | Reject bad tokens before forwarding | `routes/gateway.py` | P01, S03 |
| **P03** — Object-level authorization | Users only see their own orders | `target/` | P01 |
| **P04** — Admin hardening | Hashed admin password, login limits | `routes/auth.py` | S05 |
| **P05** — Automatic bans | Ban after repeated violations | `security/ban_manager.py`, new `security/abuse.py` | S03 |
| **P06** — Attack suite | Scripts that perform each attack | new `attacks/` | All of Part A, then P00–P05 |
| **P07** — Dashboard updates | Show new events and settings | `frontend/` | P04, P05 |

### P00 — Replay protection

An attacker who captures a signed request can resend it, and it's accepted again.

- The gateway adds `X-Timestamp` and `X-Nonce` (a random value) headers, and includes both in the signature.
- The target rejects requests older than a set window (for example 30 seconds) and requests whose nonce it has already seen.
- Store seen nonces only until their timestamp expires, so the store doesn't grow forever.

**Done when:** tests show a resent request is rejected, an old timestamp is rejected, and a tampered timestamp breaks the signature.

### P01 — User authentication

The target's login returns the literal string `"mock access token"`.

- Login checks the bcrypt password hash (already partly done) and returns a real signed token with an expiry and the user's identity, either an HMAC-signed token or a JWT.
- Routes that act on user data require `Authorization: Bearer <token>`.
- Add a `customer_id` to each user so tokens can be tied to orders in P03.

**Done when:** tests cover valid login, a wrong password, missing, tampered, and expired tokens, and a protected route rejecting each bad token.

### P02 — Gateway token checks

Defense in depth: the gateway verifies user tokens before forwarding, so requests with invalid tokens never reach the target.

- Protected routes reject missing, tampered, or expired tokens with `401`, and log them as `blocked` / `invalid_token`.
- Optionally, rate limit per user as well as per IP.

**Done when:** a request with a bad token is rejected and logged at the gateway, and the target receives nothing.

### P03 — Object-level authorization

`GET /orders/{customer_id}` returns any customer's orders. This is the top item in the OWASP API Security Top 10 (Broken Object Level Authorization).

- The target uses the customer ID from the token, not the URL. Either change the route to `GET /orders/me`, or return `403` when the URL's ID doesn't match the token.
- Apply the same rule to placing orders, so users can't create orders for other customers.

**Done when:** tests show user A can read their own orders and gets `403` for user B's.

### P04 — Admin hardening

- Store the admin password as a bcrypt hash in `.env` instead of plaintext, and add a small command to generate the hash.
- Limit `/admin/login` attempts per IP, for example 5 per minute.

**Done when:** tests show the hashed password works, plaintext isn't stored anywhere, and excess login attempts get `429`.

### P05 — Automatic bans

Bans currently happen only when an admin adds one manually.

- Count violations per IP: rate-limit hits, invalid input, and failed logins.
- When an IP reaches a configurable threshold within a time window, call `ban_ip` automatically and log the reason.
- Make the threshold and window editable through `/admin/settings`.

**Done when:** tests show the ban triggers at exactly the threshold, not one violation earlier, and the banned IP is blocked afterward.

### P06 — Attack suite

Scripts in `attacks/` that each perform one attack and report whether it succeeded:

| Script | Attack | Expected on v1.0 | Expected on v2 |
|---|---|---|---|
| `forge_signature.py` | Sign a request with an empty or guessed key | Succeeds | Blocked |
| `bypass_gateway.py` | Call the target directly | Succeeds | Blocked |
| `replay.py` | Resend a captured signed request | Succeeds | Blocked |
| `idor_orders.py` | Read another customer's orders | Succeeds | Blocked |
| `brute_force_login.py` | Guess passwords repeatedly | Rate limited only | Auto-banned |
| `flood.py` | Send requests far over the limit | Rate limited | Rate limited, then auto-banned |

Run every script against the `v1.0` tag and the final code. The before-and-after table is the main result for the report.

**Done when:** every script runs with one command and prints a clear succeeded/blocked result.

### P07 — Dashboard updates

Once P04 and P05 are finished, update the dashboard to show the new log reasons (`invalid_token`, `replay`, `auto_ban`), automatic bans, and the new settings. As before, generate the frontend against the finished API, not a guessed one.

---

## Stretch goals

Only if Parts A and B are finished:

- API keys for client applications, stored hashed, with per-key rate limits.
- Per-route policies, such as stricter limits on `/login` than `/orders`.
- Docker Compose with HTTPS, so the whole stack runs with one command.

## Suggested split for four people

- **Person 1:** S00, S01, S03, then P00 (signing, forwarding, replay protection).
- **Person 2:** S02, S04, then P01 and P03 (target hardening, user auth, authorization).
- **Person 3:** S05, S06, then P04 and P05 (admin hardening, automatic bans).
- **Person 4:** P02, then P06 (gateway token checks, attack suite), and P07 at the end.

S00 blocks Persons 1 and 2, so do it first. Person 4 can start the attack scripts against `v1.0` right away, since those attacks already work on the old code.