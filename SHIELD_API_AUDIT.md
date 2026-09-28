# Shield-API scope and implementation-plan audit

Prepared September 26, 2026. This audits the repository baseline and corrects the planning documents; it does **not** report implemented security features or completed application tests.

Repository baseline: [`Vroonster20/API-Shield`, commit `423c58447d2c4224e37c8e23197bc3b3f2e0d9ea`](https://github.com/Vroonster20/API-Shield/tree/423c58447d2c4224e37c8e23197bc3b3f2e0d9ea), inspected on `main`. Links below pin that baseline rather than a moving branch.

## 1. Repository evidence

| Evidence | Finding | Required response |
|---|---|---|
| [README](https://github.com/Vroonster20/API-Shield/blob/423c58447d2c4224e37c8e23197bc3b3f2e0d9ea/README.md) | Describes the intended protection features, administrator controls, ban durations, and a UI action to run fuzzing tests. | Trace those requirements through contracts, tasks, tests, and demonstrations. Documentation is a statement of intent, not implementation evidence. |
| [Backend entry point](https://github.com/Vroonster20/API-Shield/blob/423c58447d2c4224e37c8e23197bc3b3f2e0d9ea/backend/main.py) | Starter FastAPI application with a root endpoint. | Preserve FastAPI; add the gateway and separate management application deliberately. The starter endpoint is not an API protection pipeline. |
| [Backend files](https://github.com/Vroonster20/API-Shield/tree/423c58447d2c4224e37c8e23197bc3b3f2e0d9ea/backend) | Requirements declare FastAPI/Pydantic, but do not declare the required Uvicorn or FastAPI CLI startup dependency. | Choose and explicitly declare the server command/dependency; verify installation and startup from a clean environment. |
| [TypeScript entry point](https://github.com/Vroonster20/API-Shield/blob/423c58447d2c4224e37c8e23197bc3b3f2e0d9ea/src/index.ts) | Console greeting rather than an administrator interface. | Build the UI with the existing TypeScript foundation; plain TypeScript plus Vite is sufficient. |
| [Package manifest](https://github.com/Vroonster20/API-Shield/blob/423c58447d2c4224e37c8e23197bc3b3f2e0d9ea/package.json) | Typecheck command contains `tsc --noEmiti`; `@prisma/client` is unused and has no accompanying Prisma schema. | Correct the command to `tsc --noEmit`; reconcile/remove unused dependencies as an explicit implementation task. |
| [Environment example](https://github.com/Vroonster20/API-Shield/blob/423c58447d2c4224e37c8e23197bc3b3f2e0d9ea/backend/.env.example) | Contains a MySQL placeholder, conflicting with the proposed SQLite design. | Replace the placeholder with the chosen SQLite/operator settings during implementation; do not maintain two unexplained persistence stacks. |

At this baseline, rate limiting, automatic bans, request validation, the control panel, the fuzz runner, and security logging are not implemented. This audit changes no application source files.

## 2. Main findings in the previous plan

1. **Automatic bans were missing.** The plan had rate counters and IP lists, but no abuse thresholds, temporary-ban state, expiry semantics, management operations, or ban tests. A rate-limit response alone does not satisfy automatic banning.
2. **Fuzzing was missing as a UI feature.** Malformed-input tests did not provide the README's “Run fuzzing test” action. Both a controlled runner and its UI/API contract are needed.
3. **Optional work dominated the mandatory path.** JWT verification, multiple services, monitor mode, gateway-owned CORS, extensive revision workflows, and advanced operational tooling increased effort before the five core features were complete.
4. **The proposed stack was not reconciled with the starter repository.** React, a mandatory `uv` workflow, and a new dependency layout were assumptions. Preserve FastAPI and TypeScript; pin requirements and establish reproducible commands without requiring a package-manager migration.
5. **Feature traceability was incomplete.** Each requirement needs a runtime contract, a bounded implementation task, observable acceptance tests, and an end-to-end demonstration.

The accompanying plan, task board, test matrix, and example configuration are being revised around these findings. They remain implementation instructions, not evidence that the repository already satisfies them.

## 3. Core course MVP

Use one protected API service/host, FastAPI, plain TypeScript/Vite, and SQLite. Preserve existing application authentication through the gateway. Support configuration-driven routes so login, signup, cart, and another JSON endpoint use the same engine.

| Feature | Core contract | Task ownership | Acceptance evidence |
|---|---|---|---|
| Rate limiting | Persistent fixed-window IP attempt limits; atomic admission; no quota refund after later failure. | T06, integrated into the gateway in T08 | Concurrent limit boundary, retry time, separate identities, restart, and storage-failure checks. |
| Abuse detection and bans | One strike per request for `RATE_LIMITED`, `INVALID_JSON`, or `SCHEMA_REJECTED`; default threshold 10 within 60 seconds. With `auto_ban_enabled=true`, create a 300-second temporary ban. Default `false` records detection without automatic bans. Manual bans and revoke are available. | T08, T10, T13 | Exact threshold, detection-only behavior, concurrent strikes, expiry, restart, manual action, and zero origin receipts for banned admissions. |
| Input validation | Always-enforced byte/content-type/strict-JSON/restricted-schema checks on configured routes; accepted body bytes preserved. | T07, integrated into the gateway in T08 | Invalid syntax/types/bounds block safely; valid requests retain their original bytes; resource bounds remain effective. |
| UI fuzzing | A button starts a fixed synthetic suite against an isolated demo fixture: one active job, at most 100 cases, at most 60 seconds. | T12, T13, T14 | Correct job lifecycle, bounded execution/results, busy/restart handling, case outcomes, and isolation from real API data and counters. |
| Control panel | Secure login; versioned configuration editing; rate/ban settings; active bans/revoke; events; fuzz controls/results. | T09, T10, T13 | Real authenticated workflow; stale-edit conflict; CSRF/session checks; changes affect gateway behavior as specified. |
| Security logging | Bounded metadata events and administrative audit records; distinguish rate, ban, validation, gateway, and origin outcomes. | T11, T10, T13 | Secret-marker tests, bounded retention/failure handling, correct decision categories, and truthful UI counts. |

The fuzz runner accepts a predefined profile identifier only. It does not accept arbitrary URLs, request templates, payload uploads, scripts, or shell commands. It must not silently mutate live signup/cart data or ban ordinary users. Developer Hypothesis tests supplement this feature; they do not replace the UI runner.

## 4. Simplifications and retained security requirements

| Previous requirement | Revised scope |
|---|---|
| Multiple services and hostname onboarding | One configured service/host; prove generality through different endpoint policies. |
| JWT verification and per-subject limits | Defer; preserve origin credentials and use trusted client-IP identity. |
| Draft CRUD, desired/applied workflow, diff, restore UI | Full configuration PUT with `expected_version`, validation, and atomic active revision. Each request uses one consistent configuration. |
| Route monitor mode | Defer; core request validation is enforced. Detection-only automatic-ban configuration is a separate, explicit setting. |
| Gateway-managed CORS | Defer; the core demonstration is same-origin. |
| Live-backup CLI and broad production tooling | Defer automation; document persistence, supported deployment limits, and safe operational procedures. |
| Complex charts and extensive performance campaign | Prioritize working controls, event/results tables, and reproducible core checks. |
| ML, replay analysis, arbitrary-origin scanning, origin failed-login classification | Defer; use explicit gateway-observed strike reasons and the isolated fuzz fixture. |

The smaller scope **retains** secure administrator cookies and CSRF protection, bounded bodies/time/concurrency, trusted client-IP handling, approved destinations, origin isolation, correct cookie/header forwarding, no unsafe retries, atomic database state, failure behavior, and secret-free logs. These are prerequisites for a usable security gateway.

## 5. Implementation and validation gates

The revised task board uses T00–T17: reconciliation, contracts, database, configuration/compiler, proxy harness, gateway, rate limits, validation, abuse/bans, administrator authentication, control endpoints, logs, fuzz runner, UI, demo, packaging, release checks, and handoff.

- **T00–T03:** establish the actual startup commands, remove stack contradictions, freeze contracts, and migrate empty storage. The sample configuration must use only core features.
- **T04–T08 and T11:** prove transport fidelity, rate behavior, validation, ban transitions, and sanitized events against a receipt-counting origin. Interface scaffolds must not be mistaken for a completed gateway.
- **T09–T10 and T13:** verify session/CSRF protection and a real configuration/ban/log control workflow. No production mock fallback.
- **T12 and T14:** demonstrate bounded isolated fuzzing, case results, and reusable endpoint policies. Keep synthetic fixtures separate from real API data.
- **T15–T17:** verify clean startup, persisted state, exposure boundaries, every core matrix check, and a second contributor's installation/demo walkthrough.

Task dependencies must distinguish initial gateway scaffolding from final composition: rate, validation, abuse, and event modules can depend on frozen contracts, while the completed gateway depends on their implementations. Do not introduce a circular “gateway requires policies; policies require completed gateway” dependency.

Use the revised [implementation plan](SHIELD_API_PLAN.md), [task board](SHIELD_API_TASKS.md), and [test matrix](SHIELD_API_TEST_MATRIX.md) together. Completion requires recorded test results and a working demonstration of all five requested feature areas. Later implementation or review may reveal additional gaps; record and resolve those without silently expanding the course scope.
