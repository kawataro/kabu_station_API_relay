from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from ..models import PriceChangeResponse, PriceChangeRow
from ..repositories import price_changes as pc_repo


router = APIRouter(prefix="/v1")


@router.get("/price-changes", response_model=PriceChangeResponse)
async def price_changes(
    request: Request,
    symbol: str = Query(..., description="symbol or api_symbol"),
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
) -> PriceChangeResponse:
    settings = request.app.state.settings
    rows = pc_repo.history(
        settings.storage.db_path,
        symbol=symbol,
        from_iso=from_,
        to_iso=to,
        limit=limit,
    )
    return PriceChangeResponse(
        count=len(rows),
        rows=[PriceChangeRow.model_validate(r) for r in rows],
    )
