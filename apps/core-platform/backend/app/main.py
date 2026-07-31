"""Application entrypoint.

Run locally:   uvicorn app.main:app --reload
Run in Docker: see deployment/docker-compose.yml (backend service)
"""

from app.core.registrar import register_app

app = register_app()
