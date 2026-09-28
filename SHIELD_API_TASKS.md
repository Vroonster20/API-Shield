# Shield-API: 18 core implementation assignments

Implementation has begun. Treat the tasks below as contracts; consult [implementation evidence](docs/shield-api/IMPLEMENTATION_STATUS.md) before assigning work so completed modules are not rebuilt. Remaining work is listed there explicitly.

This replaces the earlier 22-task enterprise-leaning board. All tasks below belong to the five-feature course MVP. Optional JWT, distributed deployment, live scanners, server drafts, rollback UI and complex charts must not be added. These are instructions for future implementation, not completed tasks.

Read [the specification](SHIELD_API_PLAN.md), [audit](SHIELD_API_AUDIT.md), and [acceptance matrix](SHIELD_API_TEST_MATRIX.md). The specification owns behavior and field names. A coordinator owns shared contracts, migrations, dependencies and final gateway composition. Give other agents disjoint files. Implement one bounded task at a time; report contradictions instead of inventing new behavior or bypasses.

## Dependency graph and parallel work

```text
T00 -> T01
T01 -> T02, T04
T01 + T02 -> T03, T06, T09, T11
T01 + T03 -> T07
T03 + T04 -> T05
T02 + T06 -> T08
T03 + T08 + T09 + T11 -> T10
T04 + T05 + T07 -> T14
T05 + T06 + T07 + T08 + T11 + T14 -> T12
T10 + T12 -> T13
T10 + T12 + T13 + T14 -> T15
T05 + T06 + T07 + T08 + T10 + T11 + T12 + T13 + T14 + T15 -> T16
T16 -> T17
```

T05 builds the transport/routing skeleton against T01 interfaces; it does not depend on later protection modules. T06/T07/T08 are independently tested providers of those interfaces. **The coordinator integrates providers into the actual gateway at the end of T08 once T05/T07/T11 are available, and before T12/T14 end-to-end claims.** Test-only injected fakes never become public allow-all defaults. T14 can build its origin independently before gateway integration. This distinction avoids a circular dependency.

Parallel owners after T01: gateway/transport (T04–T05), storage/protection (T02/T06/T08), management/UI (T09/T10/T13), validation/demo/testing (T07/T11/T12/T14). Team members may execute multiple tasks sequentially. An agent may scaffold UI against frozen fixtures after T01; final T13 completion requires real APIs.

## Commands T00 must establish

Commands are intended interfaces to create, not claims about existing scripts. From repository root in the activated virtual environment:

```text
python -m pip install -r backend/requirements-dev.txt
python -m ruff check backend
python -m pytest backend/tests/unit -q
python -m pytest backend/tests/integration -q
python -m pytest backend/tests/network -q
python -m pytest backend/tests/fuzz -q
npm ci
npm run typecheck
npm run build
npm run test:e2e
python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8081
python -m uvicorn gateway:app --app-dir backend --host 127.0.0.1 --port 8080 --no-proxy-headers
```

The requirements-dev file includes runtime requirements plus test tools. Document venv creation and Windows activation. Use python -m imports rather than assuming globally installed executables. Tests run only against isolated synthetic state; all production entry points require real config/protection providers or return unready.

## T00 — Reconcile starter and establish runnable commands

**Depends:** none. **Own:** root package/tsconfig/lockfiles, backend dependency files and entry points, README setup, CI skeleton. **Read:** spec1–2, audit repository table.

1. Inspect actual branch and preserve changes made since audited commit; record any differences before changing structure.
2. Fix `--noEmiti`, set browser DOM/bundler TypeScript options and add Vite/index.html. Preserve root npm workflow; no separate React project.
3. Keep FastAPI, declare Uvicorn and actually used backend packages, lock compatible versions. Replace MySQL example with local SQLite/HMAC-secret-path settings and remove unused Prisma only after usage check.
4. Create separate management/gateway entry points with minimal health and no public management mounting. Add skeleton directories from spec11.
5. Add gitignore patterns for SQLite/WAL/SHM, secrets, temp reports and test caches. Add CI install/lint/typecheck/build/unit entry points.
6. Verify linked SQLite fix gate and document local runtime path outside OneDrive. Do not implement application features here.

**Validate:** E01–E03. **Done:** second contributor can install/start skeleton using documented commands; invalid runtime/config exits safely.

## T01 — Freeze contracts and golden fixtures

**Depends:** T00. **Own:** contracts.py, docs/contracts.md, sample fixtures and generated/frontend API type source. **Read:** spec3–11.

1. Implement strict Config/Route/RateLimit/AbuseConfig, API response/error, BanView, FuzzSummary/CaseResult, Admission and Violation models with exact names/ranges.
2. Define immutable config and injectable clock, registry, secret, transport and event interfaces. No hidden global request state.
3. Parse the core sample; invalid fixtures cover unknown fields, wrong types, invalid bounds, unsupported schema and duplicate IDs. Require sample to remain free of deferred features.
4. Freeze canonical settings-hash serialization, HTTP status/reason codes, state enums, pagination and nullable fields.
5. Keep typed API interfaces in src/api.ts synchronized with the Python contracts and verify actual response shapes in integration/browser tests. Automatic type generation is optional for this small MVP; do not let UI guess field names.

**Validate:** C01–C03. **Done:** module agents can use contracts and synthetic fixtures without inventing shapes. No source implementation depends on a placeholder accept-all policy.

## T02 — SQLite schema and transaction helpers

**Depends:** T01. **Own:** db.py, migrations, repository primitives, DB tests. **Read:** spec5–6,8,10.

1. Create all listed tables, checks, indexes and numbered/checksummed migrations. Run migration once, outside server startup races.
2. Configure local WAL, foreign_keys per connection, total bounded write-lock budget and serialized transaction ownership.
3. Provide read repositories and short write helpers with guaranteed rollback/mutex release on error or cancellation. No shared connection transaction interleaving.
4. Implement monotonic-effective durable clock helper, retention/capacity primitives and cleanup batches. Never evict active counters/bans.
5. Support atomic security-event insertion in caller-owned transactions. Keep optional traffic batches separate.

**Validate:** D01–D04. **Done:** no handler needs raw SQL or can leave partial protection/config mutations.

## T03 — Config compiler, atomic apply and runtime snapshot

**Depends:** T01,T02. **Own:** config.py and compiler/reload tests. **Read:** spec3,8.

1. Validate registry reference, hostname/path grammar, route overlaps, body limits, IDs and restricted schemas; compile a complete frozen object.
2. Freeze service ID after initial apply; preserve stable route IDs and limiter namespaces.
3. Implement apply(expected_version,document): compile first, compare expected version in write transaction, insert revision+desired pointer+security record atomically.
4. Implement polling, swap and applied acknowledgment, startup-unready state, failure-version association and heartbeat. Clear stale errors correctly.
5. Keep existing requests on captured snapshot; enforce one gateway runtime lock. No server drafts or rollback endpoints.

**Validate:** C01–C05,V01–V05. **Done:** settings apply without partial config or false UI acknowledgment.

## T04 — Receipt-counting local origin harness

**Depends:** T01. **Own:** backend/tests network fixtures and demo test-support module. **Read:** spec4 and acceptance P01–P08.

1. Create local real HTTP fixtures for echo bytes/query, multiple cookies, binary/gzip, arbitrary statuses, redirect, timeout/disconnect and side-effecting POST.
2. Record receipt count, raw target/header pairs/body for synthetic test assertions only. Test inspection/reset is private to runner, never public origin routes.
3. Start/stop fixtures on ephemeral loopback ports with temporary state and guaranteed cleanup.
4. Provide the same isolated fixture primitives to the future fuzz worker, without live registry/DB imports.

**Validate:** direct-origin self-checks; P01–P03 fixtures demonstrate raw evidence. **Done:** proxy tests can prove forwarding fidelity and zero origin receipts on blocks.

## T05 — Gateway identity/routing and correct proxy skeleton

**Depends:** T03,T04. **Own:** proxy.py and gateway envelope/routing modules; coordinator owns composition. **Read:** spec4.

1. Implement strict host/path/peer identity and optional single-edge trust. Disable framework auto-proxy headers; preserve pending route404/405 for later baseline evaluation.
2. Build lifespan HTTPX pool with fixed registry destination, no redirects/retries/env proxies/TLS bypass.
3. Forward original path/query/body bytes and end-to-end header pairs; handle Connection nominations and multiple Set-Cookie; prevent cookie persistence/crossover and strip admin cookies.
4. Enforce request/response/time/pool bounds and preserve no-body status/method semantics.
5. Implement stream ownership/finally cleanup and total-lifetime handling, including cancellation/backpressure.
6. Wire typed admission/validation/event interfaces through dependency injection. Until concrete providers are integrated, ordinary public requests return503, never unrestricted proxying.

**Validate:** I01–I03,P01–P08 using explicit test providers. **Done:** transport is independently correct and ready for coordinator integration.

## T06 — Atomic fixed-window rate provider

**Depends:** T01,T02. **Own:** protection/rate module and rate tests. **Read:** spec5.

1. Derive canonical IP digest and stable settings hash; inject persistent secret and clock.
2. Implement applicable baseline/route counter consumption in caller-owned short transaction; saturate L+1, count all attempts reaching stage, no refund.
3. Return all violated budgets and maximum Retry-After. No HTTP IO or JSON parsing here.
4. Preserve counters on restart/name edits; settings changes create specified namespaces. Enforce capacity and clock rules.
5. Expose atomic composition hooks so T08 can add pre-rate ban check and strike recording in the same transaction, not nested independent commits.

**Validate:** R01–R07. **Done:** exactly configured allowance can pass concurrent attempts; store failure has explicit typed result.

## T07 — Bounded body and JSON/schema validation

**Depends:** T01,T03. **Own:** validation.py, validation unit/generated fixtures. **Read:** spec7 runtime checks.

1. Count actual bytes/deadline in receive wrapper; media-type rules include empty body and vendor JSON cases.
2. Reject unsupported request compression; parse strict UTF-8/JSON, duplicate keys and nonfinite numbers without rewriting original bytes.
3. Enforce numeric/depth/node/schema bounds and unsupported-keyword/ref rejection. No network/file schema resolution.
4. Return INVALID_JSON/SCHEMA_REJECTED versus INSPECTION_LIMIT_EXCEEDED distinctly so abuse engine counts only its defined signals.
5. Bound inspection pool and cancellation cleanup; collect no more than allowed safe errors, never input values.

**Validate:** B01–B05. **Done:** accepted body unchanged; invalid input bounded and rejected before origin.

## T08 — Abuse detector, ban state and gateway integration

**Depends:** T02,T06 for engine; integration additionally T05,T07,T11. **Own:** protection/abuse/ban modules; coordinator composes gateway. **Read:** spec4–6.

1. Add ban-first admission to shared transaction, rate consumption, one rate strike/request, threshold event and optional automatic ban creation atomically.
2. Add one payload-rejection hook; recheck live ban and prevent double strikes/TTL extension under concurrency.
3. Implement detection-only default, settings fingerprint, temporary expiry, ban-capacity failures and restart persistence. No origin-status/failed-login inference.
4. Implement manual create/revoke repositories with canonical IP/digest input, existing/stale/idempotent behavior and synchronous security events.
5. Integrate concrete rate/abuse/validation/event providers into gateway in exact stage order once ready. Remove skeleton-unready state only when all required providers exist.
6. Test triggering response versus subsequent403, previously admitted requests, no quota refund on unban, no active-ban hit counters, and same client across routes.

**Validate:** BAN01–BAN10,G01–G04 plus R01–R07. **Done:** real gateway visibly demonstrates rate -> detection -> temporary ban -> expiry/revoke, with independent origin receipts.

## T09 — Administrator bootstrap, session and CSRF protection

**Depends:** T01,T02. **Own:** admin_auth.py, bootstrap/reset CLI, auth tests. **Read:** spec9.

1. Bootstrap via prompt/secret file, reviewed Argon2 parameters, no defaults/public registration.
2. Implement management ingress limits, per-IP/global login attempts and bounded off-thread hash/dummy verification.
3. Create hashed opaque sessions with exact cookie/expiry/revocation and safe development-mode rules.
4. Implement session GET/login/logout and common authentication/Origin/CSRF guards for every protected endpoint.
5. Insert authentication audit safely; secret errors never echo submitted credentials. Reset revokes sessions.

**Validate:** M01–M05. **Done:** management data/actions are inaccessible through anonymous, forged or expired requests.

## T10 — Configuration, status, bans and event APIs

**Depends:** T03,T08 engine,T09,T11. **Own:** admin_api.py handlers and API tests. **Read:** spec8–10 endpoint table.

1. Expose exact config GET/PUT/registry/status contracts using repositories; no direct live config edits.
2. Expose ban list/create/revoke with session/CSRF guards and bounded identity/duration inputs. Do not log submitted IP.
3. Expose filtered request/security events with bounded date range, stable keyset pagination, safe cursor parsing and bound SQL.
4. Distinguish desired/applied/stale/error and origin versus gateway outcomes. Include retention/loss limits.
5. Update frontend API interfaces and test every endpoint unauthenticated as well as authorized.

**Validate:** V01–V05,BAN06–BAN09,M01–M05,L01–L04. **Done:** UI can perform all settings/ban/log operations without a parallel business logic implementation.

## T11 — Redacted events, retention and runtime telemetry

**Depends:** T01,T02. **Own:** events.py and logging configuration; coordinate migrations. **Read:** spec10.

1. Build events from allowlisted fields only, never serialize a generic request/exception object.
2. Implement bounded traffic queue/batches/drop counters and bounded shutdown. Security mutations use caller transaction for critical records.
3. Implement retention/cap cleanup and status loss notice; do not delete active protection rows with logs.
4. Disable/redact unsafe default access logs, Pydantic input dumps and worker error output. Store route templates/IDs, not raw dynamic paths.
5. Seed distinct secret markers across all possible inputs and assert absence from DB/stdout/API/UI/report surfaces.

**Validate:** L01–L05. **Done:** operators can understand rate/ban/validation/fuzz/config events without exposing credentials.

## T12 — Bounded isolated fuzz runner and endpoints

**Depends:** T04,T05,T06,T07,T08 integration,T09,T11,T14 fixtures. **Own:** fuzz_jobs.py,fuzz_worker.py, fixed profiles and fuzz API handlers. **Read:** spec7 runner contract.

1. Accept only fixed profile+bounded seed; authenticate and require CSRF. Reserve one job atomically; reject overlap.
2. Launch trusted fixed worker using argument array/shell=False. It owns loopback fixture servers, separate DB/config/secrets and synthetic data. No user URL/commands/live config.
3. Build deterministic valid/malformed/boundary cases plus explicit rate/ban and cross-user authorization scenarios. Isolate ordinary cases so self-banning does not invalidate later cases.
4. Enforce case/request/rate/concurrency/deadline/output/retention caps and record receipt-delta invariants as well as HTTP statuses.
5. Persist sanitized terminal results/security event; always kill/reap/cleanup/release on failure, timeout or shutdown. Recover stale jobs as interrupted, never replay.
6. Implement start/list/detail endpoints and seeded repeatability. Keep developer Hypothesis tests separate from runtime job execution.

**Validate:** F01–F08. **Done:** control panel can run a useful synthetic fuzz suite without touching live protection or application data.

## T13 — Small control panel with all five feature workflows

**Depends:** T10,T12; scaffolding allowed after T01. **Own:** src/api.ts,views,styles,index.html; no backend contract edits. **Read:** spec9 UI areas.

1. Build typed same-origin fetch client with session/CSRF and generic error handling; no localStorage token.
2. Implement login/logout/expiry and four areas: overview/logs, settings, bans, fuzz tests. Use plain TypeScript forms/tables.
3. Settings edits full document locally, validates/saves expected_version, waits for applied status, preserves text on conflict and labels counter reset.
4. Ban controls show duration/source/expiry/digest, add/revoke and semantics of disabling future auto-ban. Do not imply raw IP identification from digest.
5. Fuzz UI labels isolated target, seed, bounded run state/results; expected rejection is a passing case, not an error.
6. Add loading/empty/error/stale states, escaped text, keyboard/focus labels and duplicate-submit protection. No production fallback to fixtures.

**Validate:** U01–U05 against actual management API. **Done:** unfamiliar teammate completes all control actions without direct DB edits or source changes.

## T14 — Synthetic application and five-feature demonstration

**Depends:** T04,T05,T07 for fixtures; full integration also T06,T08,T10. **Own:** demo/ and deterministic scenario scripts. **Read:** spec1,6–7,12.

1. Build small synthetic login/signup/cart API with application-owned credential, ownership, quantity and authoritative-price checks. Its DB is separate from Shield DB.
2. Use opaque cookie/bearer auth passed through; JWT verification is not a gateway dependency. Same-origin demo page avoids custom CORS work.
3. Supply valid login/cart, repeated rate rejection, malformed-payload strike/ban, exact expiry and manual-revoke scenarios with expected counts.
4. Add a booking/general JSON route by configuration only to demonstrate reuse; no second service required.
5. Provide deterministic test fixtures to T12 without giving it live registry/user data. Origin receipt inspection is private to test runner.

**Validate:** X01–X04. **Done:** group can demonstrate all five requested features and explain what stays in the origin.

## T15 — Local packaging, startup and operator guide

**Depends:** T10,T12,T13,T14. **Own:** scripts/,deploy/,operator docs. **Read:** spec2,8–10,12.

1. Provide reproducible start/migrate/bootstrap/stop scripts. Keep gateway worker count1 and enforce runtime lock.
2. Serve built UI from management; configure dev hosts, same-origin demo and approved origin registry.
3. Keep management/origin private, live SQLite outside synced source, secrets in separate local files. Document HTTPS requirement for remote use.
4. Provide stopped-service backup/isolated restore instructions including secret recovery/session revocation, not a new backup system.
5. If Compose simplifies teammate setup, add it; native local setup is sufficient if repeatable and exposure is controlled. Stop fuzz worker with servers.

**Validate:** E01–E03,O01–O04. **Done:** another machine can start and stop without undocumented manual fixes or public origin/admin exposure.

## T16 — Core release checks and generated tests

**Depends:** integrated T05–T15. **Own:** release tests/evidence; feature fixes coordinated with file owners. **Read:** entire matrix.

1. Run every core case at its required layer. Use real network for cookie/header/framing/timeout claims and browser for real UI.
2. Add bounded Hypothesis parser/path and rate/ban reference-model tests; seed/replay minimized failures, no external targets.
3. Test bans/config changes under concurrent traffic, lock failures, shutdown, fuzz limits and live-state isolation, and secret-marker scans.
4. Run stated local60s/concurrency20 smoke test, measure environment/results and leaks; no fixed latency promises.
5. Fix failures and rerun affected/full core checks. Record honest unresolved limits; do not label skipped work passed.

**Validate:** all matrix cases, especially F01–F08,BAN01–BAN10. **Done:** five-feature core has reproducible evidence; no known protection bypass or secret leak remains.

## T17 — Documentation and group handoff

**Depends:** T16. **Own:** README, architecture/compatibility/operator docs, release evidence.

1. Reconcile README promises with delivered subset: no generic failed-login/replay detector, arbitrary scanner, JWT engine or multi-service platform.
2. Write clean setup and10-minute demo: valid request, rate reject, temporary ban/revoke, input rejection, UI fuzz run, security logs.
3. Explain fixed-window behavior, shared-IP false positives, counter/strike/ban resets, same-origin limit and origin lockdown.
4. Have an uninvolved teammate follow instructions; fix undocumented steps.
5. Final report lists tests actually run and implemented versus deferred work. Repository publishing/PR actions are separate from this documentation audit.

**Validate:** X01–X04 and successful fresh-user walkthrough. **Done:** group can explain and operate the scoped product.

## Copyable subagent assignment and completion contract

```text
Implement task Txx only.
Read its referenced sections of SHIELD_API_PLAN.md and acceptance IDs in
SHIELD_API_TEST_MATRIX.md. Prerequisites integrated: [IDs/ref].
Own only these paths: [list]. Other agents own: [list].
The coordinator owns shared types, schema migrations, manifests and pipeline.
Do not redesign contracts/add deferred features; report exact conflicts instead.
Use temporary synthetic state. No real secrets, public test traffic or allow-all fallback.
Return: outcome; files/purpose; approved contract changes; exact commands/results;
acceptance IDs passed; unresolved gaps with task IDs. Never claim unrun tests passed.
```
