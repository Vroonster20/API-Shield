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
from fastapi import APIRouter, Request, Response, HTTPException,status
from pydantic import ValidationError
import hmac
import hashlib
import os
from app.security.validator import LoginAttempt,Order,PaymentBody
from app.security.rate_limiter import is_allowed
from app.security.ban_manager import is_banned
from app.logging.logger import log_event
import httpx
from dotenv import load_dotenv


router = APIRouter()
client = httpx.AsyncClient()

@router.get("/login")
async def gateway_login(request: Request,model: LoginAttempt):
    if not request.client:
        raise ValueError("No client found for API request")
    ip = request.client.host
    if is_banned(ip):
        log_event(ip,"/login","blocked","banned")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,detail="IP banned")
    if not is_allowed(ip):
        log_event(ip,"/login","blocked","rate-limited")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="IP ratelimited")
    try:
        model.model_validate(request.body())
    except ValidationError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,detail="Unable to process request")
    log_event(ip,"/login","allowed")

    #FORWARDING Request to target API
    body = await request.body()

    load_dotenv("./.env.example")

    hex_secret = os.getenv("SHARED_SECRET_KEY")

    if hex_secret is None:
      raise ValueError("Critical Error: 'SHARED_SECRET_KEY' environment variable is not set.")
    signature = hmac.new(bytes.fromhex(hex_secret),body,hashlib.sha256).hexdigest()

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["Gateway-Signature"] = signature

    target_url = "http://127.0.0.1:8001/login"

    forwarded_request = client.build_request(
        method = request.method,
        url=target_url,
        headers=headers,
        content=body
    )

    response = await client.send(forwarded_request)

    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=response.headers
    )
    
@router.get("/order")
async def gateway_get_orders(request:Request):
    if not request.client:
            raise ValueError("No client found for API request")
    ip = request.client.host
    if is_banned(ip):
        log_event(ip,"/orders","blocked","banned")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,detail="IP banned")
    if not is_allowed(ip):
        log_event(ip,"/orders","blocked","rate-limited")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="IP ratelimited")
    log_event(ip,"/orders","allowed")

    body = await request.body()

    load_dotenv("./.env.example")

    hex_secret = os.getenv("SHARED_SECRET_KEY")

    if hex_secret is None:
      raise ValueError("Critical Error: 'SHARED_SECRET_KEY' environment variable is not set.")
    signature = hmac.new(bytes.fromhex(hex_secret),body,hashlib.sha256).hexdigest()

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["Gateway-Signature"] = signature

    target_url = "http://127.0.0.1:8001/orders"

    request_params = request.query_params

    response = await client.get(target_url,params=request_params)

    return Response(
        content=response.content,
        status_code=response.status_code,
        headers = response.headers
        
    )    

@router.post("/db/orders")
async def gateway_place_orders(request:Request):
    if not request.client:
            raise ValueError("No client found for API request")
    ip = request.client.host
    if is_banned(ip):
        log_event(ip,"/db/orders","blocked","banned")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,detail="IP banned")
    if not is_allowed(ip):
        log_event(ip,"/db/orders","blocked","rate-limited")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="IP ratelimited")
    log_event(ip,"/db/orders","allowed")

    body = await request.body()

    load_dotenv("./.env.example")

    hex_secret = os.getenv("SHARED_SECRET_KEY")

    if hex_secret is None:
      raise ValueError("Critical Error: 'SHARED_SECRET_KEY' environment variable is not set.")
    signature = hmac.new(bytes.fromhex(hex_secret),body,hashlib.sha256).hexdigest()

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["Gateway-Signature"] = signature

    target_url = "http://127.0.0.1:8001/login"

    forwarded_request = client.build_request(
        method = request.method,
        url=target_url,
        headers=headers,
        content=body
    )

    response = await client.send(forwarded_request)

    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=response.headers
    )
@router.post("/webhooks/payments")
async def gateway_payments(request:Request):
    if not request.client:
            raise ValueError("No client found for API request")
    ip = request.client.host
    if is_banned(ip):
        log_event(ip,"/orders","blocked","banned")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,detail="IP banned")
    if not is_allowed(ip):
        log_event(ip,"/orders","blocked","rate-limited")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="IP ratelimited")
    log_event(ip,"/orders","allowed")

    body = await request.body()

    load_dotenv("./.env.example")

    hex_secret = os.getenv("SHARED_SECRET_KEY")

    if hex_secret is None:
      raise ValueError("Critical Error: 'SHARED_SECRET_KEY' environment variable is not set.")
    signature = hmac.new(bytes.fromhex(hex_secret),body,hashlib.sha256).hexdigest()

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["Gateway-Signature"] = signature

    target_url = "http://127.0.0.1:8001/orders"

    forwarded_request = client.build_request(
        method = request.method,
        url=target_url,
        headers=headers,
        content=body
    )

    response = await client.send(forwarded_request)

    return Response(
        content=response.content,
        status_code=response.status_code,
        headers = response.headers
        
    ) 
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
