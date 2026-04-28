from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import SnapshotHistoryResponse, SnapshotHistoryRow
from ..repositories import snapshots as snap_repo


router = APIRouter(prefix="/v1")


@router.get("/snapshots", response_model=SnapshotHistoryResponse)
async def snapshots_history(
    request: Request,
    symbol: str = Query(..., description="api_symbol e.g. 4582@3"),
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    cursor: Optional[str] = Query(default=None),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> SnapshotHistoryResponse:
    settings = request.app.state.settings
    if not any(s.api_symbol == symbol for s in settings.symbols):
        raise HTTPException(
            status_code=404,
            detail={
                "error": "symbol_not_found",
                "message": f"Unknown api_symbol: {symbol}",
            },
        )
    cursor_id: Optional[int] = None
    if cursor is not None:
        try:
            cursor_id = int(cursor)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_query", "message": "cursor must be an integer id"},
            )
    rows, next_cursor = snap_repo.history(
        settings.storage.db_path,
        api_symbol=symbol,
        from_iso=from_,
        to_iso=to,
        limit=limit,
        order=order,
        cursor_id=cursor_id,
    )
    return SnapshotHistoryResponse(
        symbol=symbol,
        count=len(rows),
        next_cursor=next_cursor,
        rows=[SnapshotHistoryRow.model_validate(r) for r in rows],
    )
