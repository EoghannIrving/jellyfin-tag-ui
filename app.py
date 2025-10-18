"""Compatibility module exposing the application instance."""

from __future__ import annotations

from jellyfin_tag_ui import create_app

app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
