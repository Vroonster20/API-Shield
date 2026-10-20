"""
Input validation.

Defines Pydantic models that match the ACTUAL request shapes of the
fake target API's endpoints (see backend/target/target_main.py).
"""
from pydantic import BaseModel

class PaymentDetails(BaseModel):
    id:int
    object:str
    amount: float
    amount_recieved: float
    currency: str
    status: str
    client_secret: str

class PaymentBody(BaseModel):
    id: int
    data: PaymentDetails
    request: PaymentRequest
    type : str

class PaymentRequest(BaseModel):
    id: int
    impotency_key: str

class CustomerOrderRequest(BaseModel):
    order_id: int

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

class OrderResponse(BaseModel):
    message:str
