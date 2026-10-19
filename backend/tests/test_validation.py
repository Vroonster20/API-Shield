"""
Tests for request validation models.
"""
from app.security.validator import PaymentBody,CustomerOrderRequest,LoginAttempt,Order
from pydantic import ValidationError
import unittest

class ValidatorTest(unittest.TestCase):
    def test_valid_payload_passes(self,payload:dict):
        validated_payload = PaymentBody.model_validate(payload)
        assert validated_payload.data.amount > 0
        print("TEST passed!")

    def test_missing_field_rejected(self,payload:dict):
        with self.assertRaises(ValidationError):
            validated_payload = CustomerOrderRequest.model_validate(payload)
        print("TEST passed!")


    def test_wrong_type_rejected(self,payload:dict):
        with self.assertRaises(ValidationError):
            validated_payload = CustomerOrderRequest.model_validate(payload)
        print("TEST passed!")

valid_payload = {
    "id": 908123457,
    "data": {
        "id":39075621,
        "object": "payment",
        "amount": 56.43,
        "amount_recieved": 56.43,
        "currency": "usd",
        "status": "success",
        "client_secret": "kdljfldkjfielsjkdf"
    },
    "request": {
        "id": 5637492873,
        "impotency_key": "kdslkg93857j2fjsl"
    },
    "type": "payment_intent.succeeded"
}

payload_missing_field = {
    "cust_id":9275,
    "customer_status": "SILVER",
    "date_ordered": "01-Jan-25",
    "o_id": 1258475628,
    "p_id": 1234567903,
    "quantity": 4
}

payload_wrong_type = {
    "cust_id":9275,
    "customer_status": "SILVER",
    "date_ordered": "01-Jan-25",
    "o_id": 1258475628,
    "p_id": 1234567903,
    "quantity": 4,
    "price": "LOW"
}

tester = ValidatorTest()
tester.test_valid_payload_passes(valid_payload)
tester.test_missing_field_rejected(payload_missing_field)
tester.test_wrong_type_rejected(payload_wrong_type)