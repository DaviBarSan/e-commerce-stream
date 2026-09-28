"""Reflex config. Run in production mode, where the UI and the Reflex backend share one port:

    reflex run --env prod --frontend-port 3000 --backend-port 3000

(Dev mode's React Router dev server fails to start under bun on Windows; see the store-frontend feature doc.)
"""
import reflex as rx
from reflex.plugins.sitemap import SitemapPlugin

config = rx.Config(
    app_name="store_frontend",
    frontend_port=3000,
    backend_port=3000,
    telemetry_enabled=False,
    disable_plugins=[SitemapPlugin],
)
