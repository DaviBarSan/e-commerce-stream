"""Cart: one open cart per session, stored in the database (the API is stateless)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from store_backend.identity import get_identity
from store_backend.models import Cart, CartItem, Product
from store_backend.routers import get_db
from store_backend.telemetry_hooks import emit, money

router = APIRouter(tags=["cart"])


class AddItem(BaseModel):
    product_id: str
    quantity: int = Field(1, ge=1, le=99)


class CartItemOut(BaseModel):
    product_id: str
    quantity: int
    unit_price_minor: int
    currency: str


class CartOut(BaseModel):
    cart_id: str | None
    status: str | None
    items: list[CartItemOut]
    items_count: int
    total_minor: int
    currency: str | None


def open_cart(db: Session, session_id: str) -> Cart | None:
    return db.scalar(select(Cart).where(Cart.session_id == session_id, Cart.status == "open"))


def cart_out(cart: Cart | None) -> CartOut:
    if cart is None:
        return CartOut(cart_id=None, status=None, items=[], items_count=0, total_minor=0, currency=None)
    items = [CartItemOut.model_validate(i, from_attributes=True) for i in cart.items]
    return CartOut(
        cart_id=cart.cart_id,
        status=cart.status,
        items=items,
        items_count=sum(i.quantity for i in items),
        total_minor=sum(i.quantity * i.unit_price_minor for i in items),
        currency=items[0].currency if items else None,
    )


@router.post("/cart/items", response_model=CartOut, status_code=201)
def add_item(request: Request, body: AddItem, db: Session = Depends(get_db)) -> CartOut:
    identity = get_identity(request)
    product = db.get(Product, body.product_id)
    if product is None:
        raise HTTPException(404, f"product {body.product_id} not found")
    cart = open_cart(db, identity.session_id)
    if cart is None:
        cart = Cart(cart_id=f"c-{uuid.uuid4().hex[:16]}", session_id=identity.session_id, user_id=identity.user_id)
        db.add(cart)
    item = next((i for i in cart.items if i.product_id == product.product_id), None)
    if item is None:
        cart.items.append(CartItem(product_id=product.product_id, quantity=body.quantity,
                                   unit_price_minor=product.price_minor, currency=product.currency))
    else:
        item.quantity += body.quantity
    db.commit()
    emit(request, "add_to_cart", f"/products/{product.product_id}", product_id=product.product_id,
         cart_id=cart.cart_id,
         properties={"quantity": body.quantity, "unit_price": money(product.price_minor, product.currency)})
    return cart_out(cart)


@router.delete("/cart/items/{product_id}", response_model=CartOut)
def remove_item(request: Request, product_id: str, db: Session = Depends(get_db)) -> CartOut:
    cart = open_cart(db, get_identity(request).session_id)
    item = next((i for i in cart.items if i.product_id == product_id), None) if cart else None
    if item is None:
        raise HTTPException(404, f"product {product_id} is not in the cart")
    cart.items.remove(item)
    db.commit()
    emit(request, "remove_from_cart", "/cart", product_id=product_id, cart_id=cart.cart_id, properties={})
    return cart_out(cart)


@router.get("/cart", response_model=CartOut)
def view_cart(request: Request, db: Session = Depends(get_db)) -> CartOut:
    cart = open_cart(db, get_identity(request).session_id)
    emit(request, "page_view", "/cart", properties={"page": "cart"})
    return cart_out(cart)
