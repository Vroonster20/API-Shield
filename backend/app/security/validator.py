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
from pydantic import BaseModel

# TODO [B05]: define request models matching backend/target/target_main.py
