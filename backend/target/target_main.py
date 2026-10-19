"""
[Task B02] Fake target API -- the app being "protected."

This is a small, standalone FastAPI app with its own DB. It knows
nothing about the gateway -- it just behaves like a real app would.
The gateway (app/routes/gateway.py) forwards approved requests here.

Run standalone with:
    python -m uvicorn target.target_main:app --reload --port 8001

Suggested endpoints to implement (adjust to taste):
    POST /login   -- check username/password against a users table
    GET  /orders  -- list orders for a user
    POST /orders  -- place an order (product_id, quantity)

Keep this intentionally simple -- it's a demo target, not the project
being graded.
"""
from fastapi import FastAPI, HTTPException,status,Request
from pydantic import BaseModel
import bcrypt
from datetime import datetime

import uvicorn

from target.target_db import create_target_tables,fill_user_table,get_target_db,check_username,retrieve_password,addwebhook

app = FastAPI(title="Fake Target API")

class LoginAttempt(BaseModel):
    username:str
    password:str

class LoginResponse(BaseModel):
    access_token:str
    token_type:str = 'bearer'
    username:str

class Order(BaseModel):
    cust_id:int
    customer_status:str
    date_ordered:str
    o_id:int
    p_id:int
    quantity:int
    price:float
    payment_status:str

class OrderResponse(BaseModel):
    message:str

class PaymentPayload(BaseModel):
    cust_id:int
    o_id:int
    amount:float
    status:str

@app.on_event("startup")
def on_startup():
    create_target_tables()
    fill_user_table()


@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/login",response_model=LoginResponse)
def login(credentials:LoginAttempt):
    user = check_username(credentials.username)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="incorrect username or password"
        )
    else:
        hashed_pass = retrieve_password(user)
        verified_password = False
        if hashed_pass: 
            pt_bytes = str.encode(credentials.password)
            verified_password = bcrypt.checkpw(pt_bytes,hashed_pass)

    if not verified_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="incorrect username or password"
        )

    return {
        "access_token": "mock access token",
        "token_type": "bearer",
        "username": credentials.username
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
            
@app.post("/orders",response_model=OrderResponse)
def order(placed_order:Order):
    with get_target_db() as conn:
        id_check = conn.execute('INSERT INTO orders ("Customer ID","Customer Status","Date Order was Placed","Order ID","Product ID","Quantity Ordered","Total Retail Price for This Order","Payment Status") VALUES (?,?,?,?,?,?,?) RETURNING "Customer ID"',
                     (placed_order.cust_id,placed_order.customer_status,placed_order.date_ordered,placed_order.o_id,placed_order.p_id,placed_order.quantity,placed_order.price,))
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

@app.post("/payments/webhooks",status_code=status.HTTP_200_OK)
async def payments_webhook(request:Request):
    #checks for signature from gateway
    signature = request.headers.get("X-Provider-Signature")
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Missing gateway signature"
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
        payment_object = data.get("data").get("object")
        timestamp = datetime.now()
        with get_target_db() as conn:
            id_found = conn.execute("SELECT event_id FROM webhooks WHERE event_id = ?",(data.get("data").get("object").get("id"),)).fetchone()
        if not id_found:
            addwebhook(payment_object.get("id"),timestamp)
        else:
            print("Duplicate recieved, ignoring......")


    return {"status:accepted"}
    

    
    
    
    

# TODO [B02]: add /login, /orders (or whatever endpoints fit your demo),
# matching whatever Pydantic models you define in app/security/validator.py.


if __name__ == "__main__":
    uvicorn.run(app, port=8001)