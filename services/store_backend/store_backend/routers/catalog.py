"""Catalog, search and product detail."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from store_backend.models import Product
from store_backend.routers import get_db
from store_backend.telemetry_hooks import emit, money

router = APIRouter(tags=["catalog"])


class ProductOut(BaseModel):
    product_id: str
    sku: str
    name: str
    category: str
    price_minor: int
    currency: str
    image_url: str


class ProductPage(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    page_size: int


class HomeOut(BaseModel):
    featured: list[ProductOut]
    categories: list[str]


def _out(product: Product) -> ProductOut:
    return ProductOut.model_validate(product, from_attributes=True)


@router.get("/home", response_model=HomeOut)
def home(request: Request, db: Session = Depends(get_db)) -> HomeOut:
    """Home page: the first product of each category (up to 8) and the category list."""
    categories = db.scalars(select(Product.category).distinct().order_by(Product.category)).all()
    first_ids = select(func.min(Product.product_id)).group_by(Product.category)
    featured = db.scalars(
        select(Product).where(Product.product_id.in_(first_ids)).order_by(Product.category).limit(8)
    ).all()
    emit(request, "page_view", "/", properties={"page": "home"})
    return HomeOut(featured=[_out(p) for p in featured], categories=list(categories))


@router.get("/products", response_model=ProductPage)
def list_products(
    request: Request,
    category: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ProductPage:
    query = select(Product)
    if category:
        query = query.where(Product.category == category)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Product.product_id).offset((page - 1) * page_size).limit(page_size)).all()
    emit(request, "page_view", "/catalog", properties={"page": "catalog"})
    return ProductPage(items=[_out(p) for p in rows], total=total, page=page, page_size=page_size)


@router.get("/search", response_model=ProductPage)
def search(
    request: Request,
    q: str = Query(..., min_length=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ProductPage:
    pattern = f"%{q}%"
    query = select(Product).where(or_(Product.name.ilike(pattern), Product.category.ilike(pattern)))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Product.product_id).limit(page_size)).all()
    emit(request, "search", f"/search?q={quote(q)}", properties={"query": q, "results_count": total})
    return ProductPage(items=[_out(p) for p in rows], total=total, page=1, page_size=page_size)


@router.get("/products/{product_id}", response_model=ProductOut)
def product_detail(request: Request, product_id: str, db: Session = Depends(get_db)) -> ProductOut:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, f"product {product_id} not found")
    emit(request, "product_view", f"/products/{product_id}", product_id=product_id,
         properties={"category": product.category, "price": money(product.price_minor, product.currency)})
    return _out(product)
