"""Checkout. Payment is simulated and always succeeds (failures belong to journey 7)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from store_backend.identity import get_identity
from store_backend.models import Order
from store_backend.routers import get_db
from store_backend.routers.cart import cart_out, open_cart
from store_backend.telemetry_hooks import emit, money

router = APIRouter(tags=["checkout"])


class CheckoutOut(BaseModel):
    cart_id: str
    items_count: int
    total_minor: int
    currency: str


class OrderOut(BaseModel):
    order_id: str
    cart_id: str
    total_minor: int
    currency: str


def _checkout_cart(db: Session, session_id: str):
    cart = open_cart(db, session_id)
    if cart is None or not cart.items:
        raise HTTPException(409, "no open cart with items for this session")
    return cart, cart_out(cart)


@router.post("/checkout/start", response_model=CheckoutOut)
def checkout_start(request: Request, db: Session = Depends(get_db)) -> CheckoutOut:
    cart, summary = _checkout_cart(db, get_identity(request).session_id)
    emit(request, "checkout_start", "/checkout", cart_id=cart.cart_id,
         properties={"items_count": summary.items_count,
                     "cart_total": money(summary.total_minor, summary.currency)})
    return CheckoutOut(cart_id=cart.cart_id, items_count=summary.items_count,
                       total_minor=summary.total_minor, currency=summary.currency)


@router.post("/checkout/complete", response_model=OrderOut, status_code=201)
def checkout_complete(request: Request, db: Session = Depends(get_db)) -> OrderOut:
    identity = get_identity(request)
    cart, summary = _checkout_cart(db, identity.session_id)
    order = Order(order_id=f"o-{uuid.uuid4().hex[:16]}", cart_id=cart.cart_id, user_id=identity.user_id,
                  total_minor=summary.total_minor, currency=summary.currency)
    db.add(order)
    cart.status = "converted"
    db.commit()
    emit(request, "purchase", "/checkout/confirmation", cart_id=cart.cart_id, order_id=order.order_id,
         properties={"total": money(order.total_minor, order.currency)})
    return OrderOut(order_id=order.order_id, cart_id=cart.cart_id, total_minor=order.total_minor,
                    currency=order.currency)
