"""Idempotent, deterministic seed: catalog and identified users.

Usage: python -m store_backend.seed [--products 200] [--users 20]   (reads STORE_DB_DSN)
Upserts on the natural keys (sku, email), so rerunning it changes nothing.
"""
import argparse

from sqlalchemy.dialects.postgresql import insert

from store_backend.db import create_schema, make_engine
from store_backend.models import Product, User
from store_backend.settings import Settings

CATEGORIES = ["lighting", "furniture", "kitchen", "electronics", "books", "garden", "toys", "sports"]
ADJECTIVES = ["Classic", "Modern", "Compact", "Deluxe", "Eco", "Smart", "Vintage", "Urban", "Nordic", "Pro"]
NOUNS = {
    "lighting": ["Lamp", "Pendant", "Spotlight", "Lantern"],
    "furniture": ["Chair", "Table", "Shelf", "Sofa"],
    "kitchen": ["Kettle", "Pan", "Knife Set", "Blender"],
    "electronics": ["Headphones", "Speaker", "Charger", "Keyboard"],
    "books": ["Novel", "Cookbook", "Atlas", "Guide"],
    "garden": ["Planter", "Hose", "Rake", "Bench"],
    "toys": ["Puzzle", "Robot", "Kite", "Blocks"],
    "sports": ["Racket", "Yoga Mat", "Ball", "Dumbbell"],
}


def products(count: int) -> list[dict]:
    rows = []
    for n in range(count):
        category = CATEGORIES[n % len(CATEGORIES)]
        noun = NOUNS[category][(n // len(CATEGORIES)) % len(NOUNS[category])]
        adjective = ADJECTIVES[(n * 7) % len(ADJECTIVES)]
        rows.append({
            "product_id": f"p-{n + 1:04d}",
            "sku": f"SKU-{category[:3].upper()}-{n + 1:04d}",
            "name": f"{adjective} {noun}",
            "category": category,
            "price_minor": 499 + (n * 1373) % 19500,  # 4.99 to 199.99, deterministic
            "currency": "EUR",
            "image_url": f"/static/products/p-{n + 1:04d}.png",
        })
    return rows


def users(count: int) -> list[dict]:
    return [{"user_id": f"user-{n + 1:03d}", "email": f"user{n + 1:03d}@example.com"} for n in range(count)]


def seed(dsn: str, product_count: int = 200, user_count: int = 20) -> None:
    engine = make_engine(dsn)
    create_schema(engine)
    with engine.begin() as conn:
        stmt = insert(Product).values(products(product_count))
        conn.execute(stmt.on_conflict_do_update(
            index_elements=[Product.sku],
            set_={c: stmt.excluded[c] for c in ("name", "category", "price_minor", "currency", "image_url")},
        ))
        conn.execute(insert(User).values(users(user_count)).on_conflict_do_nothing(index_elements=[User.email]))
    engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--products", type=int, default=200)
    parser.add_argument("--users", type=int, default=20)
    args = parser.parse_args()
    seed(Settings.from_env().store_db_dsn, args.products, args.users)
    print(f"seed: {args.products} products, {args.users} users")


if __name__ == "__main__":
    main()
