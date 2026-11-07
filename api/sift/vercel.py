"""Vercel entry point.

Vercel routes /api/* to this service and keeps the /api prefix (docs: vercel.com/docs/services/routing),
while the app's own routes start at /v1 (nginx strips /api in the Docker deployment). Mounting the app
under /api makes both deployments see the same routes; /api/docs keeps working through root_path.
"""

from fastapi import FastAPI

from .main import app as sift_app

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/api", sift_app)
