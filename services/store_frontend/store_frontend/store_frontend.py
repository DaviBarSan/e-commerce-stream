"""Storefront pages (spec 02 §7): home, search, product, cart, checkout, confirmation."""
import reflex as rx

from store_frontend.state import StoreState


def layout(*children) -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.hstack(
                rx.link(rx.heading("Clickstream Store", size="6"), href="/"),
                rx.spacer(),
                rx.form(
                    rx.hstack(rx.input(name="q", placeholder="Search products", id="search-input"),
                              rx.button("Search", type="submit", id="search-button")),
                    on_submit=StoreState.search,
                ),
                rx.link(rx.button("Cart", variant="soft"), href="/cart", id="cart-link"),
                width="100%", align="center",
            ),
            rx.cond(StoreState.error != "", rx.callout(StoreState.error, color_scheme="red", id="error")),
            rx.cond(StoreState.notice != "", rx.callout(StoreState.notice, color_scheme="green", id="notice")),
            *children,
            rx.text(
                "session ", rx.code(StoreState.session_id, id="session-id"),
                " · user ", rx.code(StoreState.user_id, id="user-id"),
                size="1", color="gray",
            ),
            spacing="4", width="100%",
        ),
        size="3", padding_y="4",
    )


def product_grid(products) -> rx.Component:
    return rx.grid(
        rx.foreach(products, lambda p: rx.card(
            rx.link(
                rx.vstack(rx.text(p["name"], weight="bold"), rx.text(p["category"], color="gray", size="2"),
                          rx.text(p["price"])),
                href="/products/" + p["product_id"], class_name="product-link",
            ),
        )),
        columns="4", spacing="3", width="100%",
    )


@rx.page(route="/", title="Store", on_load=StoreState.load_home)
def home() -> rx.Component:
    return layout(
        rx.heading("Featured", size="5"),
        product_grid(StoreState.featured),
        rx.hstack(rx.foreach(StoreState.categories, lambda c: rx.badge(c)), wrap="wrap"),
    )


@rx.page(route="/search", title="Search", on_load=StoreState.load_search)
def search() -> rx.Component:
    return layout(
        rx.heading("Results for “", StoreState.query, "” (", StoreState.results_total, ")", size="5",
                   id="results-heading"),
        product_grid(StoreState.results),
    )


@rx.page(route="/products/[product_id]", title="Product", on_load=StoreState.load_product)
def product() -> rx.Component:
    return layout(
        rx.cond(
            StoreState.product.contains("product_id"),
            rx.card(rx.vstack(
                rx.heading(StoreState.product["name"], id="product-name"),
                rx.text(StoreState.product["category"], color="gray"),
                rx.text(StoreState.product["price"], size="5", id="product-price"),
                rx.hstack(
                    rx.input(value=StoreState.quantity.to_string(), on_change=StoreState.set_quantity,
                             type="number", min=1, width="6em", id="quantity"),
                    rx.button("Add to cart", on_click=StoreState.add_to_cart, id="add-to-cart"),
                ),
            )),
        ),
    )


@rx.page(route="/cart", title="Cart", on_load=StoreState.load_cart)
def cart() -> rx.Component:
    return layout(
        rx.heading("Your cart", size="5"),
        rx.cond(
            StoreState.cart_items > 0,
            rx.vstack(
                rx.foreach(StoreState.cart_lines, lambda line: rx.hstack(
                    rx.text(line["product_id"]), rx.text("×", line["quantity"]), rx.text(line["line_total"]),
                    rx.button("Remove", variant="soft", color_scheme="red",
                              on_click=StoreState.remove_item(line["product_id"])),
                    class_name="cart-line", align="center",
                )),
                rx.text("Total: ", StoreState.cart_total, weight="bold", id="cart-total"),
                rx.button("Checkout", on_click=StoreState.start_checkout, id="checkout"),
            ),
            rx.text("Your cart is empty.", id="cart-empty"),
        ),
    )


@rx.page(route="/checkout", title="Checkout")
def checkout() -> rx.Component:
    return layout(
        rx.heading("Checkout", size="5"),
        rx.form(
            rx.vstack(
                rx.input(name="name", placeholder="Full name", id="checkout-name"),
                rx.input(name="email", placeholder="Email", type="email", id="checkout-email"),
                rx.input(name="address", placeholder="Address", id="checkout-address"),
                rx.button("Place order", type="submit", id="place-order"),
            ),
            on_submit=StoreState.place_order,
        ),
    )


@rx.page(route="/checkout/confirmation", title="Order confirmed")
def confirmation() -> rx.Component:
    return layout(
        rx.heading("Thank you!", size="5"),
        rx.text("Order ", rx.code(StoreState.order_id, id="order-id"), " · total ", StoreState.order_total),
        rx.link("Continue shopping", href="/"),
    )


app = rx.App()
