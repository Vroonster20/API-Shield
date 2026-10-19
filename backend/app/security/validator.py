"""
[Task B05] Input validation.

Define Pydantic models here that match the ACTUAL request shapes of the
fake target API's endpoints (see backend/target/target_main.py). FastAPI
will auto-reject anything that doesn't match with a 422 when these are
used as a route's request body type -- most of this task is just writing
accurate models, not custom validation code.

Example (adjust once B02's target endpoints are defined):

    class LoginRequest(BaseModel):
        username: str
        password: str

    class OrderRequest(BaseModel):
        product_id: int
        quantity: int
"""
from pydantic import BaseModel,ValidationError

class PaymentDetails(BaseModel):
    id:int
    object:str
    amount: int
    amount_recieved: int
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
    payment_status:str

class OrderResponse(BaseModel):
    message:str

def validate_payload(base_class:BaseModel,data:dict):
    try:
        return base_class.model_validate(data)
    except ValidationError as err:
        raise Exception(err.errors())
