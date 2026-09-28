# Operating the local MVP

Use the root README for installation. The defaults run one gateway, one private management process and an optional synthetic origin on the same machine. Keep SQLite on local disk outside synced folders. These instructions do not publish a service or change your firewall.

## Configure an existing API

1. Stop the local launcher. Back up the runtime directory and rate key before changing an existing installation.
2. Edit an operator-owned registry file with an approved upstream ID, display name, scheme, host and port. Use the existing API's internal address. The management UI receives only IDs/names and cannot supply arbitrary destination URLs.
3. Set `SHIELD_REGISTRY_FILE` to its absolute path. Restrict that file and `SHIELD_DATA_DIR` to the account running Shield. On Windows, use the directory's Security permissions; on Unix, restrict the directory to its owner. Do not commit secrets or application data.
4. Start management and the gateway with one worker each. For an existing API, omit the synthetic `demo:app` process. Point the service's `upstream_id` at the approved registry entry and set its exact lowercase `public_host` without a port.
5. Configure baseline IP and byte limits, then route rules. Methods are explicit: GET does not imply HEAD; OPTIONS needs an ordinary rule if your API uses it. Trailing slashes differ. Parameters occupy a full segment, for example `/cart/items/{item_id}`. Query parameters do not select policy.
6. Add a JSON schema only to JSON routes; choose explicit JSON media types. The supported keywords are listed in the main specification. An empty media-type list allows opaque bodies within the byte limit. Shield does not rewrite accepted bodies.
7. Save and wait for the gateway's **applied version** to match. A saved revision is only a desired version until the gateway acknowledges it. Stale heartbeat, failed apply and pending state remain visible in Overview.
8. Point the application frontend at the gateway. Verify that the origin is inaccessible directly to untrusted callers. Otherwise callers can bypass Shield. Keep application authentication, authorization and CSRF protections at the origin.

Private IP destinations are allowed because existing APIs often run on private networks. This makes the operator's registry and network egress rules part of the trust boundary. Do not register the management server, cloud metadata endpoints or untrusted destinations. Request paths cannot change the selected host. HTTP redirects are returned to callers and are never followed by the proxy.

## Identity and HTTPS

Local development identifies a client by its direct socket IP. Caller-supplied forwarding and identity headers are removed. Do not enable Uvicorn's automatic proxy-header handling; supplied startup commands disable it.

If an existing trusted edge sits in front of Shield, set only its exact network(s) in `SHIELD_TRUSTED_EDGE_CIDRS`. That edge must overwrite `X-Shield-Client-IP` with one validated client IP on every request. Shield rejects missing/multiple/invalid values from trusted peers. Never trust all IPv4/IPv6 addresses. Restrict network access to enforce this arrangement. Until configured, callers behind the same edge share its IP quota.

Remote use requires `SHIELD_MODE=production`, an exact HTTPS `SHIELD_ADMIN_ORIGIN`, and the owner's existing TLS edge. Management remains private. Production cookies require HTTPS. The origin must set application cookies for the public application host/path (or omit Domain); an internal-host cookie will not work in the browser. The gateway strips reserved Shield admin cookies before forwarding.

Core browser demonstrations use the same origin for their page and API. Existing origin CORS headers are preserved, but Shield does not generate a custom CORS response for its own errors. Cross-origin callers may not be able to read those error bodies. WebSockets, SSE, gRPC, uploads above 1 MiB, and responses above 10 MiB are outside this MVP.

## Limits, strikes and bans

- Rate limits are fixed windows. Both the service and matched route consume attempts, including attempts later rejected by payload validation. A route's numeric limit can exceed the service limit because its window can differ.
- Changing a limit or window changes its counter namespace. Renaming a rule does not. Changing abuse settings starts new strike tracking; keep service/route IDs stable.
- Rate rejection, invalid JSON and schema mismatch are strike signals. An application's 401/403 is forwarded and does not automatically count as a strike. Resource-limit rejection is not a malformed-input strike.
- Automatic banning starts disabled. Detection still records a threshold event. Enabling it creates bounded temporary bans at the configured threshold. A ban-triggering request retains its original 400/429; subsequent admissions get 403.
- Banned requests do not consume quota or extend expiry. Turning auto-ban off does not revoke existing bans. Revoke clears strikes but does not refund ordinary rate counters. An already admitted request may finish while a concurrent request creates a ban.
- Manual bans accept one IP or event digest and a duration of 30–3600 seconds. IPs are immediately converted to a keyed digest. A digest cannot be converted back to its IP; everyone sharing an IP shares its ban.
- Unavailable mandatory protection storage fails closed with 503. A burst can also exhaust the bounded request/inspection capacity. This local SQLite design is not a distributed traffic platform.

## State, logs and backup

`SHIELD_DATA_DIR/shield.sqlite3` stores settings, counters, bans, admin sessions and events. `rate.key` is the persistent HMAC key. Losing or changing it changes client identities, so existing counters and bans will no longer identify the same clients. Keep it with backups and restrict access. The synthetic origin's application database is separate.

Logs contain request IDs, configured route IDs, keyed client digests and decisions. They omit request bodies, raw query strings, dynamic paths, credentials and upstream URLs. Request logs are best-effort: a bounded queue can drop records under load or storage failure; Overview reports the drop count since gateway startup. They are not an accounting ledger. Security state changes and their audit records use the same transaction. Retention is seven days or 100,000 rows per event table; cleanup uses bounded batches. Fuzz reports keep at most 50 terminal runs for seven days.

For a stopped-service backup:

1. Stop gateway, management and any running fuzz job. If using the local launcher, Ctrl+C ends its child processes; fuzz workers detect parent termination and also have their own deadline. Confirm no process still uses the runtime directory.
2. Copy the entire runtime directory to a restricted backup location. Include any remaining `-wal`/`-shm` files and the rate key if stored separately. Copy the approved registry and record the application version. Back up the origin database separately using that application's procedure.
3. To restore, copy the backup into a **new isolated local directory**. Keep all listeners bound to loopback and point settings at that directory and recovered key. Do not overwrite a running database.
4. Run `python backend/manage.py migrate` with the same application version to check migration checksums, then `reset-password --username operator` to revoke restored admin sessions. Retain the HMAC key so rate/ban identities stay stable.
5. Start on isolated ports, verify desired/applied config, bans, login and origin routing, then stop. Only replace the intended installation after its processes are stopped. This restore walkthrough still needs an independent contributor's verification.

## Subagent maintenance handoff

Read `SHIELD_API_PLAN.md`, the relevant numbered task, `SHIELD_API_TEST_MATRIX.md`, and `IMPLEMENTATION_STATUS.md` before modifying code. Do not interpret historical plan text as permission to publish or scan an arbitrary target.

| Module | Responsibility | First tests to run after edits |
|---|---|---|
| `contracts.py`, `config.py`, `settings.py` | Strict policy models, immutable compile/apply, runtime settings | `backend/tests/unit` and `test_gateway_review.py` |
| `db.py`, migrations | Writer ownership, migrations, capacities, durable clock | `test_db.py`, `test_gateway_review.py`, auth/protection tests |
| `protection.py`, `validation.py` | Counters, strikes, ban transitions, bounded parsing/schema | `test_protection.py`, `test_validation.py`, `backend/tests/fuzz` |
| `gateway.py`, `proxy.py`, `events.py` | HTTP pipeline, fixed origin, response lifetime, safe metadata | `test_gateway_network.py`, `test_gateway_failures.py`, `test_events.py` |
| `admin_auth.py`, `admin_api.py`, `cli.py` | Admin login/session/CSRF, APIs, local operator commands | `test_admin.py`, then browser journey |
| `fuzz_jobs.py`, `fuzz_worker.py` | Isolated worker lifecycle, fixed test profile, safe results | `test_fuzz_jobs.py`, then UI fuzz action |
| `src/`, `tests/e2e/` | TypeScript control panel and browser workflows | Build and `npm run test:e2e` |
| `demo.py`, `scripts/`, docs | Synthetic origin, startup, reproducible verification | Network demo test and README walkthrough |

Keep tasks small: state the owned files, exact behavior to change, acceptance IDs and commands. Preserve public shapes unless the backend, UI, fixtures and docs are updated together. Do not mark an acceptance ID passed because a similarly named unit test exists; some IDs require multiple failure and concurrency scenarios.
