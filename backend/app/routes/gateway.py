"""
Gateway routes -- the integration point.

These endpoints mirror the fake target's real endpoints 

"""
from fastapi import APIRouter, Request, Response, HTTPException,status
from pydantic import ValidationError
import hmac
import hashlib
import os
from app.security.validator import LoginAttempt,Order,PaymentBody
from app.security.rate_limiter import is_allowed
from app.security.signing import createSignature
from app.security.ban_manager import is_banned
from app.logging.logger import log_event
import httpx
from dotenv import load_dotenv


router = APIRouter()
client = httpx.AsyncClient()

@router.post("/login")
async def gateway_login(request: Request,model: LoginAttempt):
    if not request.client:
        raise ValueError("No client found for API request")
    ip = request.client.host
    print(is_banned(ip))
    if is_banned(ip):
        log_event(ip,"/login","blocked","banned")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,detail="IP banned")
    if not is_allowed(ip):
        log_event(ip,"/login","blocked","rate-limited")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="IP ratelimited")
    body = await request.body()
    try:
        model.model_validate_json(body)
    except ValidationError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,detail="Unable to process request")
    log_event(ip,"/login","allowed")

    #FORWARDING Request to target API
    signature = createSignature(request_body=body)

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
    
@router.get("/orders")
async def gateway_get_orders(request:Request):
    raw_body = await request.body()
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

    signature = createSignature(raw_body)

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["Gateway-Signature"] = signature

    target_url = f"http://127.0.0.1:8001/orders/"

    request_params = request.query_params

    response = await client.get(target_url,params=request_params)

    return Response(
        content=response.content,
        status_code=response.status_code,
        headers = response.headers
        
    )    

@router.post("/db/orders")
async def gateway_place_orders(request:Request, model:Order):
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

    try:
        model.model_validate_json(body)
    except ValidationError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,detail="Unable to process request")
    log_event(ip,"/db/orders","allowed")

    signature = createSignature(request_body=body)

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["Gateway-Signature"] = signature

    target_url = "http://127.0.0.1:8001/db/orders"

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
async def gateway_payments(request:Request, model:PaymentBody):
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
    try:
        model.model_validate_json(body)
    except ValidationError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,detail="Unable to process request")
    log_event(ip,"/webhooks/payments","allowed")

    signature = createSignature(request_body=body)

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["Gateway-Signature"] = signature

    target_url = "http://127.0.0.1:8001/webhooks/payments"

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
