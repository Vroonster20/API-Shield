# Shield-API core acceptance matrix

This is a test specification for the five-feature course MVP in [SHIELD_API_PLAN.md](SHIELD_API_PLAN.md), assigned by [SHIELD_API_TASKS.md](SHIELD_API_TASKS.md). It is not a record of passing tests. Run only against synthetic identities, isolated state and approved local fixtures; record actual commands, outcomes and omissions in release evidence. Network cases use real HTTP sockets and a private receipt-counting origin; browser cases use the real management API. `origin receipts = 0` means the origin fixture observed no request, not merely that the gateway returned an error.

## Environment and contracts

| ID | Layer | Test and required result |
|---|---|---|
| E01 | Clean install | Create documented Python environment, install pinned backend/dev and npm dependencies, then lint, typecheck, build and start both listeners; no undeclared CLI/package dependency. |
| E02 | Startup | No config, invalid secret/registry, incompatible SQLite or second gateway worker fails safely/unready; linked SQLite fix and local non-synced runtime path are recorded. |
| E03 | Deployment | Fresh contributor follows migrate/bootstrap/start/stop instructions, reaches distinct gateway/admin hosts, and can perform an isolated stopped-service backup and restore with session revocation. |
| C01 | Contract | Exact one-service Config sample parses; unknown fields, coercion, duplicate IDs, invalid names/types/ranges and payloads over 256 KiB fail. |
| C02 | Contract | Rate, abuse, route, BanView, error, fuzz and admission shapes match the spec and typed UI interfaces; sample has inline routes and no deferred fields. |
| C03 | Contract | Stable settings-hash JSON and declared status/reason codes match deterministic fixtures; unset/null fields and pagination states have explicit types. |
| C04 | Compiler | Reject unapproved upstream, malformed host/path, duplicate/ambiguous routes, route cap above service cap, unsupported schema or schema over 16 KiB. |
| C05 | Compiler | Literal route wins over parameter route; equal-specificity overlap fails; method-specific matching, strict trailing slash and immutable service ID behave as specified. |
| D01 | SQLite | Numbered/checksummed migration runs once; schema constraints/indexes exist and foreign keys are enabled on every connection. |
| D02 | SQLite | Competing writers and forced exception/cancellation release mutex and roll back fully within the 100 ms acquisition/busy budget. |
| D03 | SQLite | Durable effective time never decreases after backward clock change; expired rows clean in batches without evicting active counters/bans. |
| D04 | SQLite | Rate/abuse/ban capacity and storage failure return protection unavailable; caller-owned security records commit atomically with state. |
| V01 | Config API | Valid full PUT with matching expected_version creates immutable revision and pending status; gateway swaps whole snapshot and acknowledges applied version. |
| V02 | Config API | Stale expected_version returns 409 CONFIG_CONFLICT; invalid document returns 422 CONFIG_INVALID; neither mutates desired/applied state. |
| V03 | Runtime | Requests spanning an apply finish on captured old snapshot; subsequent requests use new snapshot, with no partial mixed fields. |
| V04 | Runtime/UI | Failed apply keeps last good snapshot, associates error with failed version, and clears stale error on newer successful save; status precedence/heartbeat is truthful. |
| V05 | Config | Name/unrelated edits preserve rate counters; limit/window edits create new namespace and UI reset notice; abuse-setting edits reset strikes but retain live bans. |

## Gateway identity, proxy and admission

| ID | Layer | Test and required result |
|---|---|---|
| I01 | Network | Spoofed Forwarded/X-Forwarded-For/X-Real-IP/X-User-ID do not change peer identity; explicit trusted-edge header works only from configured CIDR, invalid/missing trusted value returns 400. |
| I02 | Network | Invalid Host, escapes, encoded separators/percent, backslash, dot segment, controls and repeated slash fail before origin; accepted canonical match forwards original raw target. |
| I03 | Network | Exact host and route selection; pending 404/405 consume baseline quota then respond with correct Allow; disabled/unknown host and envelope rejects allocate no counters. |
| P01 | Network | Echo fixture receives exact method, raw path/query order and duplicate keys, body bytes and permitted end-to-end header pairs once; accepted JSON is not reserialized. |
| P02 | Network | Separate Set-Cookie headers and raw gzip/binary response bytes survive; HEAD, 204 and 304 emit legal body/framing behavior. |
| P03 | Network | Cookies set for client A never appear in anonymous B request; application auth/cookies pass through, reserved admin cookies do not. |
| P04 | Network | Hop-by-hop and Connection-nominated fields are removed both ways; Authorization/Cookie nominations reject; origin Host/length and trusted metadata are rebuilt. |
| P05 | Network | Origin redirect is returned to caller without follow; failed side-effecting POST is never retried; environment proxy and TLS-bypass settings cannot redirect origin traffic. |
| P06 | Network | Pre-header timeout returns 504, network/protocol failure 502; oversized declared response returns 502 before headers, except HEAD/304 metadata. |
| P07 | Network | Overlong streamed response or total lifetime after headers aborts stream and records truncation; client disconnect/backpressure closes upstream and releases permit. |
| P08 | Network | Request/header/path/body/response, 50-in-flight, pool-wait and timeout bounds produce specified controlled codes with zero origin receipts where blocked; no leaked slots. |
| G01 | Network | Stage order is envelope/config/identity, ban, atomic rate, route error, body validation/strike, one origin forward, one completion event; zero origin receipts for blocks. |
| G02 | Integration | Protection storage/lock fault at admission or strike recording gives 503 PROTECTION_UNAVAILABLE and zero origin receipts; no fail-open provider. |
| G03 | Integration | Existing ban skips counters/strikes and blocks later admissions; request admitted before ban can finish without being retroactively blocked. |
| G04 | Integration | Health endpoints are reserved and bypass admission/events; ready reflects usable config and security store; public listener exposes no admin routes. |

## Rate, validation and bans

| ID | Layer | Test and required result |
|---|---|---|
| R01 | Unit/network | With limit L, first L qualifying IP attempts pass and L+1 returns 429 RATE_LIMITED; concurrent boundary admits exactly L. |
| R02 | Unit/network | Service and route limits both apply; a rejected attempt saturates counters at L+1, adds at most one strike, and Retry-After is positive maximum violated-window remainder. |
| R03 | Unit | Fixed UTC window boundary permits expected new-window traffic and documents possible 2L clustering; no sliding-window assertion. |
| R04 | Integration | Distinct canonical IP digests stay separate; mapped IPv6 normalization and shared NAT behavior match identity contract; submitted credentials cannot change limiter key. |
| R05 | Integration | Counters survive gateway restart and unrelated config edits; rate setting change changes settings hash without a global config-version reset. |
| R06 | Integration | Later invalid body, route outcome or origin error does not refund admission; rejected/failed attempts retain their counter effect. |
| R07 | Integration | Backward clock and cap/lock/storage faults cannot reopen quota or allow unlimited forwarding; bounded cleanup preserves live rows. |
| B01 | Network | Actual streamed bytes, 10 s receive deadline and route/service cap reject excess/slow body before origin, regardless of Content-Length. |
| B02 | Network | Content type normalization, empty-body rules, JSON media requirements and non-identity Content-Encoding produce exact accept/415 behavior. |
| B03 | Unit/network | Strict UTF-8 JSON rejects duplicates, NaN/Infinity and malformed syntax as INVALID_JSON; accepted body reaches origin byte-for-byte. |
| B04 | Unit/network | Restricted schema accepts intended object and rejects invalid types/ranges as SCHEMA_REJECTED; refs/unknown keywords and schema depth/node/size limits fail compilation. |
| B05 | Unit/network | Instance depth/nodes/numeric-token limits and two-inspection-job saturation yield bounded INSPECTION_LIMIT_EXCEEDED or controlled busy outcome without abuse strike or retained parser work. |
| BAN01 | Unit/network | Exactly RATE_LIMITED, INVALID_JSON and SCHEMA_REJECTED add one service/IP strike per request; 404, origin 401/429, resource/media and infrastructure errors add none. |
| BAN02 | Unit | Default auto_ban_enabled=false reaches threshold and emits one abuse.threshold event per fixed window without creating a ban; successes do not erase strikes. |
| BAN03 | Integration | With auto-ban enabled, exact threshold atomically creates one temporary ban/event; triggering request retains 400/429 and next request returns 403 IP_BANNED with Retry-After. |
| BAN04 | Integration | Concurrent threshold crossings create one ban; live-ban hits neither extend expiry nor spend quota/add strikes; another route for same IP is blocked. |
| BAN05 | Unit/integration | Ban expiry follows durable effective time and survives restart; expired ban stops blocking without cleanup; remaining rate quota still applies. |
| BAN06 | Admin API | Manual create accepts exactly one canonical IP or 64-hex digest, duration 30..3600 and allowed reason; stores digest only and emits atomic security event. |
| BAN07 | Admin API | Attempt to create when live ban exists returns 409 BAN_ALREADY_ACTIVE and does not silently extend TTL. |
| BAN08 | Admin API | Revoke current ID atomically clears live ban and all strikes, leaves rate counters; repeated retained revoke is idempotent, stale replaced ID is 409, unknown ID 404. |
| BAN09 | Admin API/UI | Ban list states, source, reason and expiry are accurate; UI explains shared-IP and no quota refund, and disabling auto-ban only stops future creation. |
| BAN10 | Integration | Payload rejection rechecks live ban under concurrency, records at most one strike, never replaces/extends another newly created ban; capacity fault blocks request. |

## Administrator, events and UI

| ID | Layer | Test and required result |
|---|---|---|
| M01 | Admin/API | CLI bootstrap has no default credential/public signup; valid login creates hashed opaque session, unknown user takes dummy verification path, login limits bound work. |
| M02 | Browser/API | Cookie attributes match secure host-only production and explicit loopback development modes; no bearer token in local storage or admin CORS. |
| M03 | Admin/API | Anonymous/expired/revoked sessions cannot read protected data; logout, replacement login and password reset revoke prior session within specified expiry. |
| M04 | Admin/API | Wrong/missing Origin, content type or CSRF on writes fails; correct same-origin session succeeds; login/general body/header/concurrency caps hold. |
| M05 | Admin/API | All management endpoints deny anonymous access; error bodies, cache headers and auth audit records are safe; storage/session-capacity faults return controlled errors. |
| L01 | Integration/UI | Seed unique secret markers in credentials, token, cookie, query, dynamic path, body and exception; none appear in DB, stdout/stderr, event API, UI or release report. |
| L02 | Integration | Saturated queue, failed batch write and shutdown with pending events remain bounded, expose loss count/warning, and do not bypass enforcement. |
| L03 | Admin API | Equal-time inserts paginate stably by timestamp+ID; cursor binds filters; hostile filters and out-of-range inputs cannot inject SQL or widen bounds. |
| L04 | Integration/API | Seven-day/100k-row retention and 500-row cleanup are bounded; earliest retained time and filtered totals reflect retained data. |
| L05 | Network/UI | Origin 4xx/429 versus 5xx, Shield blocks/errors and disconnects have correct decision/status/origin_attempted fields; one redacted completion event and honest telemetry coverage. |
| U01 | Browser | Login/logout, expired session during action and backend outage yield clear loading/error states without stale authenticated controls. |
| U02 | Browser | Edit full inline route settings, validate/save expected_version, await apply and handle stale conflict without discarding unsaved text; rate reset notice appears. |
| U03 | Browser | Logs/filter/page/retention/drop views agree with management API and distinguish forwarded origin outcomes from gateway blocks. |
| U04 | Browser | Bans form/list/revoke and detection-only toggle show source, digest, expiry and exact future-ban semantics against real API. |
| U05 | Browser | Fuzz button runs fixed isolated profile, prevents duplicate submission, shows terminal case outcomes/history; keyboard labels/focus and hostile text escaping work. |

## Isolated fuzzing, operations and demonstration

| ID | Layer | Test and required result |
|---|---|---|
| F01 | API | Only session+CSRF POST with `{profile_id:"core-demo-v1",seed:0..2147483647}` starts; URL/host/path/command/script/upload/live-credential fields reject. |
| F02 | API/integration | One queued/running job reservation is atomic; overlap returns 409 FUZZ_BUSY, and every terminal path releases slot. |
| F03 | Worker/network | Worker uses fixed module/argument array and separate temporary DB, config, secrets, users and loopback ports; no live registry, origin, data, counters or bans are touched. |
| F04 | Worker | Deterministic seeded suite has at most 100 cases and request starts at most 5/s, concurrency 1, whole job at most 60 s; violations fail the run. |
| F05 | Worker/network | Valid control request succeeds before cases and after cleanup; ordinary cases isolate protection state, while explicit rate/ban cases use their own state and receipt deltas. |
| F06 | API/worker | Each case records bounded expected/actual invariant/status, outcome, request ID, elapsed time and origin receipt delta; expected rejection passes when invariant holds; total report <=64 KiB. |
| F07 | Integration | Timeout, worker crash, shutdown or coordinator restart yields timed_out/interrupted/error honestly, kills/reaps worker, cleans temporary state and never replays stale job. |
| F08 | API/integration | Store failure cannot claim passed; list/detail paginate safely; retain at most 50 completed reports/7 days and never delete running job; developer Hypothesis tests remain separate. |
| O01 | Network/load | Pool and 50-request concurrency pressure plus upstream outage yield bounded 503/502/504, no unbounded wait or leaked permit; local 60 s/20-client smoke records measured environment. |
| O02 | Deployment | Public path cannot reach management or origin directly; approved internal paths can; public gateway does not mount admin handlers. |
| O03 | Deployment/network | Approved registry is sole outbound authority; controlled destination/redirect/wrong-TLS probes show no unapproved contact, redirect following or certificate bypass. |
| O04 | Deployment | Stop management, gateway and security DB separately; documented readiness/dependency behavior holds and mandatory protection never fails open. |
| X01 | Network/browser | Demo login/signup/cart valid and excessive/invalid requests show expected status, zero origin receipts for gateway blocks and visible redacted event evidence. |
| X02 | Network | Two demo users: B submits well-formed request for A's cart; origin denies ownership despite Shield schema acceptance. |
| X03 | Config/network | Add booking or other JSON route by configuration alone, with different schema/rate, and demonstrate protection without gateway code change. |
| X04 | Browser/network | Demonstrate rate rejection, threshold/temporary ban, exact expiry or manual revoke, validation rejection, UI fuzz run and logs; applied version and reset semantics are visible. |

No JWT verification, route monitor mode, server draft, rollback UI, arbitrary target scanner or live-backup CLI is an acceptance condition. A passing matrix requires recorded evidence for each ID; this document alone establishes no implementation result.
