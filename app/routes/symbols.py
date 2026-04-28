from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from ..models import SymbolListResponse, SymbolOut


router = APIRouter(prefix="/v1")


@router.get("/symbols", response_model=SymbolListResponse)
async def list_symbols(
    request: Request,
    bucket: Optional[str] = Query(default=None),
) -> SymbolListResponse:
    settings = request.app.state.settings
    items = settings.symbols
    if bucket:
        items = [s for s in items if s.bucket == bucket]
    return SymbolListResponse(
        count=len(items),
        symbols=[
            SymbolOut(
                api_symbol=s.api_symbol,
                symbol=s.symbol,
                exchange=s.exchange,
                name=s.name,
                bucket=s.bucket,
            )
            for s in items
        ],
    )
