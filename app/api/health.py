"""Health endpoint."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import Settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Public health response."""

    status: str
    service: str
    environment: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return a deterministic process health result without external API calls."""

    settings = Settings.from_env()
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        environment=settings.environment,
    )
