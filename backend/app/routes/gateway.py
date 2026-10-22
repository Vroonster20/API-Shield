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
    current_file = os.path.abspath(__file__)

    dir_lvl_1 = os.path.dirname(current_file)
    dir_lvl_2 = os.path.dirname(dir_lvl_1) 
    backend_dir = os.path.dirname(dir_lvl_2)
    env_path = os.path.join(backend_dir, '.env.example')
    load_dotenv(dotenv_path=env_path)

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
    
@router.get("/orders/{customer_id}")
async def gateway_get_orders(customer_id:int,request:Request):
    cust_id = customer_id
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

    body =b''

    current_file = os.path.abspath(__file__)

    dir_lvl_1 = os.path.dirname(current_file)
    dir_lvl_2 = os.path.dirname(dir_lvl_1) 
    backend_dir = os.path.dirname(dir_lvl_2)
    env_path = os.path.join(backend_dir, '.env.example')
    load_dotenv(dotenv_path=env_path)

    hex_secret = os.getenv("SHARED_SECRET_KEY")

    if hex_secret is None:
      raise ValueError("Critical Error: 'SHARED_SECRET_KEY' environment variable is not set.")
    signature = hmac.new(bytes.fromhex(hex_secret),body,hashlib.sha256).hexdigest()

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["Gateway-Signature"] = signature

    target_url = f"http://127.0.0.1:8001/orders/{cust_id}"

    request_params = request.query_params

    response = await client.get(target_url)

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

    current_file = os.path.abspath(__file__)

    dir_lvl_1 = os.path.dirname(current_file)
    dir_lvl_2 = os.path.dirname(dir_lvl_1) 
    backend_dir = os.path.dirname(dir_lvl_2)
    env_path = os.path.join(backend_dir, '.env.example')
    load_dotenv(dotenv_path=env_path)

    hex_secret = os.getenv("SHARED_SECRET_KEY")

    if hex_secret is None:
      raise ValueError("Critical Error: 'SHARED_SECRET_KEY' environment variable is not set.")
    signature = hmac.new(bytes.fromhex(hex_secret),body,hashlib.sha256).hexdigest()

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

    current_file = os.path.abspath(__file__)

    dir_lvl_1 = os.path.dirname(current_file)
    dir_lvl_2 = os.path.dirname(dir_lvl_1) 
    backend_dir = os.path.dirname(dir_lvl_2)
    env_path = os.path.join(backend_dir, '.env.example')
    load_dotenv(dotenv_path=env_path)

    hex_secret = os.getenv("SHARED_SECRET_KEY")

    if hex_secret is None:
      raise ValueError("Critical Error: 'SHARED_SECRET_KEY' environment variable is not set.")
    signature = hmac.new(bytes.fromhex(hex_secret),body,hashlib.sha256).hexdigest()

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
