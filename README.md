# Shield-API

**Jim Cha's first iteration — September 28, 2026**

Branch: `codex/jim-cha-iteration-1`. This is the first working course-project MVP for teammate review. All five feature areas are implemented; sustained-load performance and the remaining acceptance checks are still open. See [implementation evidence and known limitations](docs/shield-api/IMPLEMENTATION_STATUS.md).

Shield-API is a course-project HTTP gateway with configurable IP rate limits, rule-based abuse detection, temporary bans, bounded request validation, a private administrator panel, and security event logs. A separate SQLite store holds its configuration and protection state; the existing API keeps its own accounts and business data.

The current implementation is a local MVP. [Implementation evidence](docs/shield-api/IMPLEMENTATION_STATUS.md) distinguishes completed checks from remaining acceptance work. The detailed [specification](SHIELD_API_PLAN.md), [task assignments](SHIELD_API_TASKS.md), [acceptance matrix](SHIELD_API_TEST_MATRIX.md), and [original audit](SHIELD_API_AUDIT.md) explain the scope and contracts.

## What it does

| Feature | Delivered behavior |
|---|---|
| Rate limiting | Persistent fixed windows per client IP, at service and optional route level; returns 429 with Retry-After. |
| Abuse and bans | Counts gateway rate/JSON/schema rejections. Detection runs by default; optional auto-ban creates temporary bans. Admins can create and revoke bans. |
| Validation | Body limits, content types, strict JSON and a bounded JSON Schema subset; accepted bytes are forwarded unchanged. |
| Fuzz tests | The panel runs a bounded, seeded synthetic suite in a separate process and temporary database. It never scans the configured live API. |
| Control panel | Login, desired/applied settings, route policies, bans, request/security events, fuzz results. |
| Logging | Metadata-only request records plus transactional security events; no raw bodies, tokens, queries or submitted IPs. |

The same engine supports login, signup, carts, reservations and other ordinary HTTP endpoints. The origin still checks passwords, permissions, ownership, prices and application CSRF. Origin failed-login classification, replay detection, ML, JWT verification, arbitrary-target fuzzing, multiple services, WebSockets, SSE and distributed deployment are outside this MVP. Fixed windows allow a burst around a window boundary. People sharing an IP also share its limits and bans.

## Local setup (PowerShell)

Use Python 3.12 or newer and Node 24. The Python-linked SQLite must include the WAL reset fix: 3.51.3+ or the 3.50.7/3.44.6 fixed branches. Startup checks this. Tested locally with Python 3.12.14, SQLite 3.53.1 and Node 24.19.0. A Python upgrade alone does not prove the linked SQLite version.

Run from the repository root. If you already have a working `.venv`, preserve it. On a fresh machine, the `python` used to create the environment must supply a compatible SQLite. If the version check is below the required fixed releases, select a compatible interpreter before migrating; do not disable the gate.

```powershell
if (-not (Test-Path .venv\Scripts\python.exe)) { python -m venv .venv }
.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.venv\Scripts\python.exe -c "import sqlite3; print(sqlite3.sqlite_version)"
npm ci
npm run build

$env:SHIELD_MODE = "development"
$env:SHIELD_DATA_DIR = Join-Path $env:LOCALAPPDATA "shield-api"
$env:SHIELD_REGISTRY_FILE = (Resolve-Path deploy/registry.local.json).Path
$env:SHIELD_ADMIN_ORIGIN = "http://admin.localhost:8081"

.venv\Scripts\python.exe backend/manage.py migrate
.venv\Scripts\python.exe backend/manage.py bootstrap-admin --username operator
.venv\Scripts\python.exe backend/manage.py apply-config --config-file docs/shield-api/examples/storefront.snapshot.json
.venv\Scripts\python.exe scripts/start_local.py
```

Bootstrap prompts twice for a password of 12–128 characters; there is no default password. Migration generates the persistent HMAC key once without overwriting it. Repeat migration safely, but bootstrap is only for the first administrator. Use `reset-password --username operator` to replace a password and revoke sessions.

Open **http://admin.localhost:8081** for the panel and **http://api.localhost:8080** for the synthetic storefront. All three listeners bind to loopback. If your resolver does not map these names, add `127.0.0.1 admin.localhost api.localhost` to your hosts file. Keep the distinct hostnames so the admin and application cookies stay separate. For command-line requests, use `http://127.0.0.1:8080` with `Host: api.localhost`.

Ctrl+C stops the local launcher and its processes. Keep runtime files outside OneDrive, network shares and this checkout. `backend/.env.example` documents settings; it is not automatically loaded. The demo application uses its own local `shield-api-demo/application.sqlite3`, configurable with `SHIELD_DEMO_DATA_DIR`.

On macOS/Linux, create the same virtual environment, use `.venv/bin/python`, and export equivalent environment variables. For example, `SHIELD_DATA_DIR="$HOME/.local/state/shield-api"` and an absolute `SHIELD_REGISTRY_FILE`. A current SQLite build is still required. Cross-platform setup and CI have not yet been verified on another contributor's machine.

## Ten-minute demonstration

1. Sign in to the admin panel and confirm the gateway reports **applied**. Open the storefront, register a synthetic account, sign in, list products and add a notebook. Its price is set by the origin.
2. In **Settings**, change the products route to 2 requests per 60 seconds. Save and wait for applied confirmation. Repeated product requests produce 429; service and route windows are independent.
3. Set the abuse strike threshold to 2, enable automatic bans and set duration to 30 seconds. Two further rate rejections create a ban; the next request returns 403. The triggering request still returns 429.
4. In **Bans**, revoke it. Revocation clears strikes but does not refund rate counters. Disable automatic bans again or wait for the rate window before continuing. Existing bans are not removed when automatic creation is disabled.
5. Submit quantity 0 to `/cart/items` with JSON: the gateway returns 400 before the origin receives it. Valid quantity and an authenticated session still work. `/reservations` demonstrates another API type configured through the same policy model.
6. Open **Fuzz tests**, choose a seed and click **Run fuzzing test**. Inspect the 17 case results and their origin receipt counts. A deliberately blocked malformed request is a passing case.
7. In **Overview**, compare request decisions with security events for config changes, abuse thresholds, bans and fuzz completion.

## Checks and development

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check backend scripts
npm run build
npm run test:e2e
.venv\Scripts\python.exe scripts/smoke.py
```

See [implementation evidence](docs/shield-api/IMPLEMENTATION_STATUS.md) for browser setup, measured smoke results and unverified cases. The smoke script uses only temporary loopback fixtures for 60 seconds at concurrency 20. It does not exercise your configured origin.

For UI development, `npm run dev:ts` proxies management requests to the local admin server; normal demonstration uses built assets served by management. Backend scripts require the virtual environment's Python on PATH. Separate commands are `npm run start:py`, `npm run start:gateway` and `npm run start:demo`.

Read the [operator guide](docs/shield-api/OPERATIONS.md) before adapting the approved upstream registry to your own API. Keep the origin and management listener private; remote use requires HTTPS and a correctly configured trusted edge. Only the gateway is intended to receive public application traffic.
