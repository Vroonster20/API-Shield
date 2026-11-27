"""
Gateway routes -- the integration point.

These endpoints mirror the fake target's real endpoints 

"""
from fastapi import APIRouter, Request, Response, HTTPException,status
from pydantic import ValidationError
from app.core.config import settings
from app.security.validator import LoginAttempt,Order,PaymentBody
from app.security.rate_limiter import is_allowed
from app.security.signing import createSignature
from app.security.ban_manager import is_banned
from app.logging.logger import log_event
import httpx
from httpx import Timeout,TimeoutException
from dotenv import load_dotenv


router = APIRouter()
client = httpx.AsyncClient()

async def fowardGET(headers:dict[str,str], route:str,params):
    target_url = settings.target_api_url + route

    timeout = Timeout(10.0,connect=3.0)

    try: 
        response = await client.get(target_url,headers=headers,params=params,timeout=timeout)
    except TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail= "Target timeout"
        )
    return response

async def fowardPOST(body:bytes, headers:dict[str,str], method:str, route:str):
    target_url = settings.target_api_url + route
    timeout = Timeout(10.0,connect=3.0)

    forwarded_request = client.build_request(
            method = method,
            url=target_url,
            headers=headers,
            content=body,
            timeout=timeout
        )
    try:
        response = await client.send(forwarded_request)
    except TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Target timeout"
        )
    return response

@router.post("/login")
async def gateway_login(request: Request):
    route = b"/login"
    route_str = "/login"
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
        LoginAttempt.model_validate_json(body)
    except ValidationError:
        log_event(ip,"/login","blocked","incorrect format")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,detail="Unable to process request")
    log_event(ip,"/login","allowed")

    #FORWARDING Request to target API
    signature = createSignature(request_body=body,route=route)

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["Gateway-Signature"] = signature

    response = await fowardPOST(body=body,headers=headers,route=route_str,method=request.method)
    return Response(
            content=response.content,
            status_code=response.status_code,
            headers = response.headers  
    )
    
@router.get("/orders")
async def gateway_get_orders(request:Request):
    route = b"/orders"
    route_str = "/orders"
    if not request.client:
            raise ValueError("No client found for API request")
    ip = request.client.host
    if is_banned(ip):
        log_event(ip,"/orders","blocked","banned")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,detail="IP banned")
    if not is_allowed(ip):
        log_event(ip,"/orders","blocked","rate-limited")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="IP ratelimited")
    params = dict(request.query_params)
    if "Customer ID" not in params.keys() or len(params.keys())> 1:
        log_event(ip,"/orders","blocked","incorrect format")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,detail="Unable to process request")
    log_event(ip,"/orders","allowed")
    raw_body = await request.body()

    signature = createSignature(request_body=raw_body,route=route)

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["Gateway-Signature"] = signature

    response = await fowardGET(headers=headers,route=route_str,params=request.query_params)

    return Response(
                content=response.content,
                status_code=response.status_code,
                headers = response.headers  
        )

@router.post("/db/orders")
async def gateway_place_orders(request:Request):
    route = b"/db/orders"
    route_str = "/db/orders"
    if not request.client:
            raise ValueError("No client found for API request")
    ip = request.client.host
    if is_banned(ip):
        log_event(ip,"/db/orders","blocked","banned")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,detail="IP banned")
    if not is_allowed(ip):
        log_event(ip,"/db/orders","blocked","rate-limited")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="IP ratelimited")
    body = await request.body()
    try:
        Order.model_validate_json(body)
    except ValidationError:
        log_event(ip,"/db/orders","blocked","incorrect format")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,detail="Unable to process request")
    log_event(ip,"/db/orders","allowed")

    signature = createSignature(request_body=body,route=route)

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["Gateway-Signature"] = signature
    
    response = await fowardPOST(body=body,headers=headers,route=route_str,method=request.method)
    return Response(
            content=response.content,
            status_code=response.status_code,
            headers = response.headers  
        )

@router.post("/webhooks/payments")
async def gateway_payments(request:Request):
    route = b"/webhooks/payments"
    route_str= "/webhooks/payments"
    if not request.client:
            raise ValueError("No client found for API request")
    ip = request.client.host
    if is_banned(ip):
        log_event(ip,"/webhooks/payments","blocked","banned")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,detail="IP banned")
    if not is_allowed(ip):
        log_event(ip,"/webhooks/payments","blocked","rate-limited")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="IP ratelimited")
    body = await request.body()
    try:
        PaymentBody.model_validate_json(body)
    except ValidationError:
        log_event(ip,"/webhooks/payments","blocked","incorrect format")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,detail="Unable to process request")
    log_event(ip,"/webhooks/payments","allowed")

    signature = createSignature(request_body=body,route=route)

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["Gateway-Signature"] = signature
    
    response = await fowardPOST(body=body,headers=headers,route=route_str,method=request.method)
    return Response(
            content=response.content,
            status_code=response.status_code,
            headers = response.headers  
        )
