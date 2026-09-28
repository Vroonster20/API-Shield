# Implementation and verification evidence

Jim Cha's first iteration, prepared September 28, 2026 on `codex/jim-cha-iteration-1`. This branch is a working course-project MVP for teammate review; performance and acceptance work listed below remains open. The original audit describes the starter baseline, while this file describes the resulting code. Tests use synthetic data and loopback fixtures. The recorded implementation checks were run September 27, 2026.

## Delivered scope

All five requested feature areas have an implementation: persistent service/route IP rate limits; rule-based strikes and automatic/manual temporary bans; request validation and isolated fuzz tests; an authenticated control panel; and security logging. The synthetic storefront demonstrates signup, login, cart ownership and a reservation endpoint through the same configurable gateway.

The stack remains FastAPI, plain TypeScript/Vite and SQLite. The management listener and public gateway are separate apps. Extra features deferred in the plan remain deferred. TypeScript API interfaces are maintained alongside the Python contracts and exercised by integration/browser tests; a separate type-generation system was not added.

| Plan tasks | Implemented files and behavior |
|---|---|
| T00–T03 | Requirements/lockfiles, explicit Uvicorn commands, strict contracts, operator settings, SQLite migration/checksums, config compiler, desired/applied revisions and single-gateway lock. |
| T04–T08 | Real socket harness, strict gateway envelope/identity/routing, streaming fixed-destination proxy, persistent fixed-window counters, bounded JSON/schema checks, detection/ban/revoke transitions. |
| T09–T11 | Argon2 admin bootstrap/reset, opaque sessions, Origin/CSRF checks, login counters, management APIs, safe metadata queue, transactional security records and bounded retention. |
| T12–T14 | Fixed seeded 17-case worker in an isolated process, run/status/results UI, control-panel settings/bans/logs, separate synthetic application database and reusable endpoint policies. |
| T15 | Local startup script, registry/environment examples, README walkthrough and stopped-service backup/restore instructions. |
| T16–T17 | Automated checks and documentation are present. Remaining release acceptance work below is explicit; the full 85-row matrix is not certified complete. |

## Commands and evidence

Runtime: Windows, Python 3.12.14, linked SQLite 3.53.1, Node 24.19.0. Runtime/dev requirements are pinned separately. SQLite's required WAL fix is checked before opening protection storage. The system Python on this machine had a different SQLite version, so checks use the project's `.venv`.

| Check | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` | Passed: 75 tests in 27.73 seconds. This count is pytest cases, not completed acceptance-matrix rows. |
| `.venv\Scripts\python.exe -m ruff check backend scripts` | Passed. |
| `.venv\Scripts\python.exe -m pip check` | Passed; no broken requirements. |
| `npm run build` | Passed: TypeScript typecheck and Vite production build. |
| `npm run test:e2e` | Passed: 1 real Edge workflow in 11.6 seconds on the final code, including all 17 fuzz cases and logout. Populated Settings screenshot visually checked. |
| `.venv\Scripts\python.exe scripts/smoke.py` | Completed 60.08 seconds at concurrency 20 with the default 100 ms writer budget. Exact results below. |

This machine's bundled Node runtime has no global npm binary, so npm commands were executed through `node .tools/npm/package/bin/npm-cli.js`. That local ignored tool bootstrap is not a project dependency. Contributors with a standard Node installation use ordinary npm commands.

The tests cover strict contracts/config/compiler boundaries, atomic DB rollback and clock behavior, cancellation during connection setup and BEGIN, rate/ban behavior and generated reference-model cases, parser/schema properties, authenticated admin APIs, exact-origin/CSRF checks, session expiry/revocation, cookie flags, malformed inputs, pagination, and CLI migration/bootstrap/reset/apply.

Real network tests verify original request body/path/query bytes, credential/application-cookie forwarding, reserved-admin-cookie removal, separate Set-Cookie headers, no shared cookie leakage, no redirect following, compressed bytes, HEAD/204/304 handling, rejected-request origin counts, timeout/connection failures, oversized/aborted streams, upstream close/permit cleanup, client disconnect, inspection saturation, missing-config readiness and exclusive gateway startup. The storefront test proves authoritative pricing and cross-user cart isolation remain in the origin.

The real fuzz subprocess passes **17 cases**, including both valid controls, malformed/schema/body-cap blocks, signup/login/cart cases, a cross-user cart denial, rate rejection and automatic ban. Tests check no live config/counter/ban/request-log mutation, worker deadline/EOF/lock handling, stale restart, sanitized bounded reports and early startup failure. The synthetic fixture freezes policy time inside a rate window and uses a 1,000 ms fixture-only DB budget to avoid testing disk scheduling accidentally. Live gateway budget/overload behavior is exercised separately at 100 ms; response statuses and origin receipts remain strict. Developer Hypothesis checks use 100 examples per property. These are checked invariants, not a general vulnerability certification.

The browser test uses the real management API and gateway: sign in, edit/save/apply settings, reject malformed JSON, create/revoke a ban, view security events, run the isolated suite to `PASSED · 17 passed · 0 failed · 0 errors`, then sign out. No API response mocks are used. A screenshot is saved to `test-results/control-panel.png` during the run.

## Load result and material limit

The first load check exposed a connection-setup cancellation leak. The implementation now lets SQLite connection setup finish and disposes of cancelled work safely. Regression tests exercise cancellation both during creation of the raw SQLite handle and during PRAGMA setup. The repeated smoke check exited successfully, removed its temporary database and returned all 50 gateway permits.

| Metric | Repeated smoke result |
|---|---:|
| Duration / concurrency | 60.08 seconds / 20 |
| Total requests | 9,697 |
| Forwarded 200 responses / matching origin receipts | 1,378 / 1,378 |
| Fail-closed 503 responses | 8,319 |
| Request event drops reported by bounded logger | 7,847 |
| End-to-end latency p50 / p95 / p99 | 110.00 / 188.00 / 297.00 ms |
| Transport errors or unexpected 500s | 0 |
| All permits returned / temporary state cleaned | Yes / yes |

**This local implementation saturates SQLite well before serving this unpaced 20-client load reliably.** Do not describe the smoke run as a throughput or production-readiness pass. The fixed writer budget was not increased to hide contention. Logging is deliberately best-effort and reports loss. Low-rate demo workflows work; profiling transaction cost and reducing DB round trips is the next performance task if the group needs more capacity. This does not require adding Redis or distributed infrastructure to the current course scope.

## Remaining acceptance work

These items are not reported as passed merely because a related unit test exists:

1. A second contributor's clean installation, demo and isolated backup/restore walkthrough (E01/E03/O-series). Current setup was verified on this Windows environment; the included CI workflow and macOS/Linux setup have not run here. CI must also provide SQLite with the required fix.
2. Complete the remaining combinations in the 85-row acceptance matrix: raw HTTP framing/duplicate-header variants, trusted-edge deployment, simultaneous config swaps during active streams, disk-full/power-loss scenarios, and broader capacity/fault injection. Existing tests cover representative cases, not every combination.
3. Additional browser coverage for two-tab config conflicts, expired-session form recovery, keyboard/mobile layouts and hostile text rendering. Current backend guards and the main browser journey pass; these specific browser journeys remain unrun.
4. Performance profiling and a stated deployment workload. The measured SQLite contention and log loss above are a real limitation, not a hidden skipped check.
5. Verify the intended deployment's HTTPS, proxy trust, origin isolation and upstream cookie/CORS configuration. No external/public deployment was performed.

The original architectural choices remain intentionally small: one configured service and gateway worker, local SQLite, no app-account/JWT engine, no arbitrary remote fuzz target, and no distributed scaling work. Follow the [operator guide](OPERATIONS.md) and the numbered task contracts for subsequent changes.

## Reproduce browser checks

Run `npm ci` and `npm run build` first. On Windows the test uses installed Edge and `.venv\Scripts\python.exe`. On other systems it uses `.venv/bin/python` and Playwright Chromium; install that browser with `npx playwright install chromium`. Set `PYTHON` to override the interpreter or `PLAYWRIGHT_BROWSER_CHANNEL` to choose an installed channel. Ports 18761/18762 must be free. Tests create and delete their own runtime directory and synthetic admin.

Run browser and Python fuzz integration tests sequentially. The worker's machine-wide lock deliberately prevents overlapping synthetic workers, including workers launched by separate test runners.
