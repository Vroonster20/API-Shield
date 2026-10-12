"""
[Task B02] Fake target API -- the app being "protected."

This is a small, standalone FastAPI app with its own DB. It knows
nothing about the gateway -- it just behaves like a real app would.
The gateway (app/routes/gateway.py) forwards approved requests here.

Run standalone with:
    python -m uvicorn target.target_main:app --app-dir [YOUR FULL PATH TO BACKEND FOLDER] --reload --port 8001

Suggested endpoints to implement (adjust to taste):
    POST /login   -- check username/password against a users table
    GET  /orders  -- list orders for a user
    POST /orders  -- place an order (product_id, quantity)

Keep this intentionally simple -- it's a demo target, not the project
being graded.
"""
from fastapi import FastAPI, HTTPException,status
from pydantic import BaseModel
import bcrypt

from target.target_db import create_target_tables,fill_user_table,get_target_db,check_username,retrieve_password

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
    price:float

class OrderResponse(BaseModel):
    message:str

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
        pass_query = retrieve_password(credentials.username)
        password = pass_query.fetchall()
        if len(password) > 1:
            print(f"ERROR singular user has {len(password)} password")
            verified_password=False
        else:
            hashed_pass = password[0]  
            pt_bytes = str.encode(credentials.password)
            verified_password = bcrypt.checkpw(pt_bytes,hashed_pass)

    if not verified_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="incorrect username or password"
        )

    return {
        "access_token": f"mock-token-for-{credentials.username}",
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
                    "Total Retail Price for This Order FROM orders
                    WHERE "Customer ID" = ?'
                    """
        orders = conn.execute(query, (customer_id,))
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
        id_check = conn.execute('INSERT INTO orders ("Customer ID","Customer Status","Date Order Placed","Order ID","Product ID", "Quantity","Price") VALUES (?,?,?) RETURNS "Customer ID"',
                     (placed_order.cust_id,placed_order.customer_status,placed_order.date_ordered,placed_order.o_id,placed_order.p_id,placed_order.price,))
        if id_check:
            return {
                "message": "Order recieved successfully!"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Order insert failed"
            )
# TODO [B02]: add /login, /orders (or whatever endpoints fit your demo),
# matching whatever Pydantic models you define in app/security/validator.py.
