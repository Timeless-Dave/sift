"""ASGI entry point: `uvicorn sift.main:app`."""

from .http.app import create_app

app = create_app()
