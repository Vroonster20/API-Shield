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
`username` and `password` as query parameters to `POST /admin/login`, matching
the FastAPI handler shape described in the backend task. Cookie-based sessions
are included automatically; if the login response contains a `token`,
`session_token`, or `access_token`, the dashboard sends it as a Bearer token.

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

The admin login, admin routes, and fuzz runner in the current backend are
stubs. Until those backend tasks are implemented and the gateway includes the
routers, sign-in and dashboard requests will show the gateway's actual error
instead of fabricated data.
