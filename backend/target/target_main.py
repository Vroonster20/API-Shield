"""
Fake target API -- the app being "protected."

This is a small, standalone FastAPI app with its own DB. It knows
nothing about the gateway -- it just behaves like a real app would.
The gateway (app/routes/gateway.py) forwards approved requests here.

Run standalone with:
    python -m uvicorn target.target_main:app --reload --port 8001
"""
from fastapi import FastAPI, HTTPException,status,Request
import bcrypt
import os
from datetime import datetime
from contextlib import asynccontextmanager
import hmac
import hashlib
from dotenv import load_dotenv

import uvicorn

if __package__:
    from .target_db import (
        addwebhook,
        check_username,
        create_target_tables,
        fill_user_table,
        get_target_db,
        retrieve_password,
    )
else:
    from target_db import (
        addwebhook,
        check_username,
        create_target_tables,
        fill_user_table,
        get_target_db,
        retrieve_password,
    )

app = FastAPI(title="Fake Target API")


@asynccontextmanager
async def lifespan(app:FastAPI):
    create_target_tables()
    fill_user_table()
    yield


@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/login")
async def login(data:Request): 
    body = await data.json()

    load_dotenv("./.env.example")
    secret_key = os.getenv("SHARED_SECRET_KEY")
    if secret_key is None:
        raise ValueError("Critical Error: 'SHARED_SECRET_KEY' environment variable is not set.")
    signature = data.headers.get("Gateway-Signature")
    body_for_verification = await data.body()
    computed_hmac = hmac.new(bytes.fromhex(secret_key),body_for_verification,hashlib.sha256).hexdigest()
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Missing gateway signature"
        )
    else:
        verify_hmac = hmac.compare_digest(computed_hmac,signature)
        if not verify_hmac:
            raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Signature not accepted"
        )

    given_user = body.get("username")
    user = check_username(given_user)
    print("got username")

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="incorrect username or password"
        )
    else:
        print("getting pass")
        hashed_pass = retrieve_password(user)
        print(hashed_pass)
        verified_password = False
        if hashed_pass:
            pt = body.get('password')
            print(pt)
            if pt is None:
                raise ValueError("Username or Password cannot be None")
            pt_bytes = str.encode(pt)
            print(pt_bytes)
            verified_password = bcrypt.checkpw(pt_bytes,hashed_pass)

    if not verified_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="incorrect username or password"
        )

    return {
        "access_token": "mock access token",
        "token_type": "bearer",
        "username": given_user
    }

@app.get("/orders/{customer_id}")
def get_orders(customer_id:int):
    customer_orders = []
    with get_target_db() as conn:
        query = """
                    SELECT "Order ID","Date Order was placed",
                    "Product ID", "Quantity Ordered",
                    "Total Retail Price for This Order" FROM "orders"
                    WHERE "Customer ID" = ?
                    """
        orders = conn.execute(query, (customer_id,))
        if not orders:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Customer ID not found"
            )
        for order in orders:
            o_id,date_placed, p_id, quantity, price = order
            customer_orders.append({
                "Order ID":o_id,
                "Date Order Placed": date_placed,
                "Product ID": p_id,
                "Quantity": quantity,
                "Price":price
            })
    return customer_orders
            
@app.post("/db/orders")
async def order(request:Request):

    load_dotenv("./.env.example")
    secret_key = os.getenv("SHARED_SECRET_KEY")
    if secret_key is None:
        raise ValueError("Critical Error: 'SHARED_SECRET_KEY' environment variable is not set.")
    signature = request.headers.get("Gateway-Signature")
    body_for_verification = await request.body()
    computed_hmac = hmac.new(bytes.fromhex(secret_key),body_for_verification,hashlib.sha256).hexdigest()
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Missing gateway signature"
        )
    else:
        verify_hmac = hmac.compare_digest(computed_hmac,signature)
        if not verify_hmac:
            raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Signature not accepted"
        )

    data = await request.json()
    with get_target_db() as conn:
        id_check = conn.execute('INSERT INTO orders ("Customer ID","Customer Status","Date Order was Placed","Order ID","Product ID","Quantity Ordered","Total Retail Price for This Order") VALUES (?,?,?,?,?,?,?) RETURNING "Customer ID"',
                     (data.get("cust_id"),data.get("customer_status"),
                      data.get("date_ordered"),data.get("o_id"), 
                      data.get("p_id"), data.get("quantity"),
                      data.get("price"),))
        id = id_check.fetchone()
        if id:
            return {
                "message": "Order recieved successfully!"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Order insert failed",
            )

@app.post("/webhooks/payments",status_code=status.HTTP_200_OK)
async def payments_webhook(request:Request):
    
    #checks for signature from gateway
    load_dotenv("./.env.example")
    secret_key = os.getenv("SHARED_SECRET_KEY")
    if secret_key is None:
        raise ValueError("Critical Error: 'SHARED_SECRET_KEY' environment variable is not set.")
    signature = request.headers.get("Gateway-Signature")
    body = await request.body()
    computed_hmac = hmac.new(bytes.fromhex(secret_key),body,hashlib.sha256).hexdigest()
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Missing gateway signature"
        )
    else:
        verify_hmac = hmac.compare_digest(computed_hmac,signature)
        if not verify_hmac:
            raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST, 
                        detail="Signature not accepted"
                    )
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid json format"
        )
    
    event_type = data.get("type")
    if event_type=="payment_intent.succeeded":
        payment_object = data.get("data").get("id")
        timestamp = datetime.now()
        with get_target_db() as conn:
            id_found = conn.execute("SELECT event_id FROM webhooks WHERE event_id = ?",(data.get("data").get("id"),)).fetchone()
        if not id_found:
            addwebhook(payment_object,timestamp)
        else:
            print("Duplicate recieved, ignoring......")


    return {"status:accepted"}


if __name__ == "__main__":
    uvicorn.run("target_main:app", port=8001, reload=True)