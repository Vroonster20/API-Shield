"""
Tests for request validation models.
"""
import pytest
from pydantic import ValidationError

from app.security.validator import LoginAttempt, Order, PaymentBody

VALID_PAYMENT = {
    "id": 908123457,
    "data": {
        "id": 39075621,
        "object": "payment",
        "amount": 56.43,
        "amount_recieved": 56.43,
        "currency": "usd",
        "status": "success",
        "client_secret": "kdljfldkjfielsjkdf",
    },
    "request": {"id": 5637492873, "impotency_key": "kdslkg93857j2fjsl"},
    "type": "payment_intent.succeeded",
}

VALID_ORDER = {
    "cust_id": 9275,
    "customer_status": "SILVER",
    "date_ordered": "01-Jan-25",
    "o_id": 1258475628,
    "p_id": 1234567903,
    "quantity": 4,
    "price": 19.99,
}


def test_valid_payment_passes():
    payment = PaymentBody.model_validate(VALID_PAYMENT)
    assert payment.data.amount == 56.43


def test_valid_order_passes():
    order = Order.model_validate(VALID_ORDER)
    assert order.quantity == 4


def test_order_missing_field_rejected():
    payload = {k: v for k, v in VALID_ORDER.items() if k != "price"}
    with pytest.raises(ValidationError):
        Order.model_validate(payload)


def test_order_wrong_type_rejected():
    payload = {**VALID_ORDER, "price": "LOW"}
    with pytest.raises(ValidationError):
        Order.model_validate(payload)


def test_login_missing_password_rejected():
    with pytest.raises(ValidationError):
        LoginAttempt.model_validate({"username": "admin"})