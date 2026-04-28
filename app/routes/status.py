from __future__ import annotations

from fastapi import APIRouter, Request

from ..status_service import build_status


router = APIRouter(prefix="/v1")


@router.get("/status")
async def status(request: Request) -> dict:
    return build_status(
        request.app.state.settings,
        request.app.state.token_manager,
        request.app.state.collector,
    )
