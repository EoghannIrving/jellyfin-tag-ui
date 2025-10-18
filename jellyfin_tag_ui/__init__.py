"""Jellyfin Tag UI application factory."""

from __future__ import annotations

from flask import Flask

from .config import PROJECT_ROOT, load_environment
from .logging import configure_logging
from .routes import apply, items, libraries, main, tags, users


def create_app() -> Flask:
    """Create and configure the Flask application."""
    load_environment()
    configure_logging()

    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )

    app.register_blueprint(main.bp)
    app.register_blueprint(users.bp)
    app.register_blueprint(libraries.bp)
    app.register_blueprint(tags.bp)
    app.register_blueprint(items.bp)
    app.register_blueprint(apply.bp)

    return app
