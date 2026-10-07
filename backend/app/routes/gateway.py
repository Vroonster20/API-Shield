"""
[Task B07] Gateway routes -- the integration point.

These endpoints mirror the fake target's real endpoints (see
backend/target/target_main.py). Each one should, in order:
  1. check app.security.ban_manager.is_banned(ip)      -> 403 if banned
  2. check app.security.rate_limiter.is_allowed(ip)     -> 429 if rate-limited
  3. validate the request body (app.security.validator models) -> 422 if invalid
  4. app.logging.logger.log_event(...) the outcome
  5. forward the request to settings.target_api_url and return its response

Keep this file as the "wiring" layer -- the actual logic lives in the
security/ and logging/ modules so it's independently testable.
"""
from fastapi import APIRouter, Request

router = APIRouter()

# TODO [B07]: add one route per protected target endpoint, e.g.:
#
# @router.post("/login")
# async def gateway_login(request: Request, body: LoginRequest):
#     ip = request.client.host
#     if is_banned(ip):
#         log_event(ip, "/login", "blocked", "banned")
#         raise HTTPException(status_code=403, detail="Banned")
#     if not is_allowed(ip):
#         log_event(ip, "/login", "blocked", "rate_limit")
#         raise HTTPException(status_code=429, detail="Rate limited")
#     log_event(ip, "/login", "allowed")
#     # forward to settings.target_api_url + "/login" via httpx, return response
