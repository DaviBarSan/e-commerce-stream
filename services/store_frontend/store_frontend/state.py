"""Storefront state. Every tracked action is a store API call; the API emits the events (spec 02 §7)."""
import uuid
from urllib.parse import quote, urlsplit

import reflex as rx

from store_frontend import api


def _product_card(p: dict) -> dict[str, str]:
    return {"product_id": p["product_id"], "name": p["name"], "category": p["category"],
            "price": api.price(p["price_minor"], p["currency"])}


class StoreState(rx.State):
    # Identity kept in the browser: user_id survives reloads and visits; session_id is per tab session.
    user_id: str = rx.LocalStorage("", name="clickstream_user_id")
    session_id: str = rx.SessionStorage("", name="clickstream_session_id")

    error: str = ""
    notice: str = ""
    featured: list[dict[str, str]] = []
    categories: list[str] = []
    query: str = ""
    results: list[dict[str, str]] = []
    results_total: int = 0
    product: dict[str, str] = {}
    quantity: int = 1
    cart_lines: list[dict[str, str]] = []
    cart_total: str = ""
    cart_items: int = 0
    order_id: str = ""
    order_total: str = ""

    # --- helpers ------------------------------------------------------------------------------

    def _identity(self) -> api.Identity:
        if not self.user_id:
            self.user_id = f"anon-{uuid.uuid4()}"
        if not self.session_id:
            self.session_id = f"s-{uuid.uuid4()}"
        url = urlsplit(str(self.router.url))
        page_url = url.path + (f"?{url.query}" if url.query else "")
        return api.Identity(session_id=self.session_id, user_id=self.user_id, page_url=page_url or "/")

    def _call(self, method: str, path: str, **kwargs):
        self.error, self.notice = "", ""
        try:
            return api.call(method, path, self._identity(), **kwargs)
        except api.ApiError as exc:
            self.error = str(exc)
        except Exception as exc:  # the API is down or unreachable
            self.error = f"The store is unavailable ({type(exc).__name__})"
        return None

    def _set_cart(self, cart: dict) -> None:
        self.cart_lines = [{"product_id": i["product_id"], "quantity": str(i["quantity"]),
                            "unit_price": api.price(i["unit_price_minor"], i["currency"]),
                            "line_total": api.price(i["unit_price_minor"] * i["quantity"], i["currency"])}
                           for i in cart["items"]]
        self.cart_items = cart["items_count"]
        self.cart_total = api.price(cart["total_minor"], cart["currency"])

    # --- page loads ---------------------------------------------------------------------------

    def load_home(self):
        data = self._call("GET", "/home")
        if data:
            self.featured = [_product_card(p) for p in data["featured"]]
            self.categories = data["categories"]

    def load_search(self):
        self.query = self.router.url.query_parameters.get("q", "")
        self.results, self.results_total = [], 0
        if self.query:
            data = self._call("GET", "/search", params={"q": self.query})
            if data:
                self.results = [_product_card(p) for p in data["items"]]
                self.results_total = data["total"]

    def load_product(self):
        product_id = urlsplit(str(self.router.url)).path.rstrip("/").rsplit("/", 1)[-1]
        self.product, self.quantity = {}, 1
        data = self._call("GET", f"/products/{quote(product_id)}")
        if data:
            self.product = _product_card(data)

    def load_cart(self):
        data = self._call("GET", "/cart")
        if data:
            self._set_cart(data)

    # --- actions ------------------------------------------------------------------------------

    def search(self, form_data: dict):
        q = (form_data.get("q") or "").strip()
        if q:
            return rx.redirect(f"/search?q={quote(q)}")

    def set_quantity(self, value: str):
        self.quantity = max(1, int(value)) if value.isdigit() else 1

    def add_to_cart(self):
        data = self._call("POST", "/cart/items",
                          json={"product_id": self.product["product_id"], "quantity": self.quantity})
        if data:
            self._set_cart(data)
            self.notice = f"Added to cart ({self.cart_items} items)"

    def remove_item(self, product_id: str):
        data = self._call("DELETE", f"/cart/items/{quote(product_id)}")
        if data:
            self._set_cart(data)

    def start_checkout(self):
        if self._call("POST", "/checkout/start"):
            return rx.redirect("/checkout")

    def place_order(self, form_data: dict):
        # Name, email and address are only validated here; payment is simulated (spec 02 §2).
        if not all((form_data.get(k) or "").strip() for k in ("name", "email", "address")):
            self.error = "Please fill in your name, email and address"
            return None
        data = self._call("POST", "/checkout/complete")
        if data:
            self.order_id = data["order_id"]
            self.order_total = api.price(data["total_minor"], data["currency"])
            return rx.redirect("/checkout/confirmation")
