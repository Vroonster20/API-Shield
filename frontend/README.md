# API Shield frontend

The admin dashboard provides Login, Overview, Request logs, IP bans, Settings,
and Fuzz testing pages. It uses the gateway's documented `/admin/*` endpoints
directly and does not include mock API data.

## Run

```bash
npm install
npm run dev
```

By default the dashboard connects to `http://127.0.0.1:8000`. You can change
the gateway URL on the login screen, or set `VITE_API_BASE_URL` before starting
the frontend.

Sign in with the gateway admin credentials. The login request sends
`username` and `password` as a JSON body to `POST /admin/login`. The login
screen is enabled by default; set `VITE_ENABLE_LOGIN=false` only to return to
the unauthenticated preview mode. Cookie-based sessions are included
automatically; if the login response contains a `token`,
`session_token`, or `access_token`, the dashboard sends it as a Bearer token.

For a frontend hosted on another origin, add that origin to the backend's
`CORS_ALLOWED_ORIGINS` JSON list in `backend/.env` and restart the backend.

The pages use these gateway endpoints:

| Page | Endpoint(s) |
|---|---|
| Overview | `GET /admin/logs`, `GET /admin/bans`, `GET /admin/settings` |
| Request logs | `GET /admin/logs` |
| IP bans | `GET /admin/bans`, `POST /admin/bans`, `DELETE /admin/bans/{id}` |
| Settings | `GET /admin/settings`, `PUT /admin/settings` |
| Fuzz testing | `POST /admin/fuzz` |

Settings use the `rate_limit_requests`, `rate_limit_window_seconds`, and
`ban_duration_seconds` fields from the backend configuration. The dashboard
expects log and ban collections as arrays (or under `logs`, `bans`, `items`,
or `results`), and fuzz results as an array (or under `results`, `cases`,
or `items`).

The backend implements all of the endpoints above. Fuzz runs send a small,
fixed set of safe requests to the gateway's own health and routing/validation
routes, then display the expected and actual HTTP status for each case.
Dashboard tables and settings are populated from the gateway API; empty
states are shown when the gateway has no records yet.

The fuzz runner targets `GATEWAY_BASE_URL` from the backend environment
(default `http://127.0.0.1:8000`). Set it to the gateway's reachable URL if
the backend listens on a different address or port.
