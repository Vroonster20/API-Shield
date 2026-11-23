import hmac
import hashlib
import os
from dotenv import load_dotenv
from fastapi import HTTPException,status

def createSignature(request_body,route:bytes):
    current_file = os.path.abspath(__file__)
    
    dir_lvl_1 = os.path.dirname(current_file)
    dir_lvl_2 = os.path.dirname(dir_lvl_1)         
    backend_dir = os.path.dirname(dir_lvl_2)
    env_path = os.path.join(backend_dir, '.env')
    load_dotenv(dotenv_path=env_path)
    
    hex_secret = os.getenv("SHARED_SECRET_KEY")
    
    if hex_secret is None:
        raise ValueError("Critical Error: 'SHARED_SECRET_KEY' environment variable is not set.")
    elif hex_secret == "":
        raise ValueError("Critical Error: 'SHARED_SECRET_KEY' environment variable is empty")
    signature = hmac.new(bytes.fromhex(hex_secret),request_body + route,hashlib.sha256).hexdigest()
    return signature

def validateKey(given_sig,request_body):
    if given_sig is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail = "no signature in request headers"
        )
    current_file = os.path.abspath(__file__)
        
    dir_lvl_1 = os.path.dirname(current_file)
    dir_lvl_2 = os.path.dirname(dir_lvl_1)                 
    backend_dir = os.path.dirname(dir_lvl_2)
    env_path = os.path.join(backend_dir, '.env')
    load_dotenv(dotenv_path=env_path)
        
    hex_secret = os.getenv("SHARED_SECRET_KEY")

    if not hex_secret:
        raise EnvironmentError("Critical Error: 'SHARED_SECRET_KEY' environment variable is not set.")
    elif hex_secret == "":
        raise ValueError("Critical Error: 'SHARED_SECRET_KEY' environment variable is empty")
    computed_hmac = hmac.new(bytes.fromhex(hex_secret),request_body,hashlib.sha256).hexdigest()
    verify_hmac = hmac.compare_digest(computed_hmac,given_sig)
    if not verify_hmac:
        raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, 
        detail="Signature not accepted"
    )