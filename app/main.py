"""FastAPI application entrypoint for Gheras Social Router."""

from fastapi import FastAPI

from app import __version__
from app.api.health import router as health_router
from app.config import Settings


def create_app() -> FastAPI:
    """Create the HTTP application without requiring external credentials."""

    settings = Settings.from_env()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )
    app.include_router(health_router)
    return app


app = create_app()
