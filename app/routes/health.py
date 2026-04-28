from __future__ import annotations

from fastapi import APIRouter, Request

from ..models import HealthResponse


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        ok=True,
        service=settings.service.name,
        version=settings.service.version,
    )
