from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from ..collector import staleness_label
from ..models import BoardsBulkResponse, LatestSnapshot
from ..repositories import snapshots as snap_repo


router = APIRouter(prefix="/v1")


def _attach_freshness(snap: dict, now: datetime, stale_threshold: float) -> dict:
    collected_at = snap.get("collected_at_utc")
    label = staleness_label(collected_at, now)
    snap["stale"] = (label == "stale")
    if collected_at:
        try:
            t = datetime.fromisoformat(collected_at)
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            snap["freshness_ms"] = max(0, int((now - t).total_seconds() * 1000))
        except ValueError:
            snap["freshness_ms"] = None
    return snap


@router.get("/boards/{api_symbol}", response_model=LatestSnapshot)
async def latest_board(api_symbol: str, request: Request) -> LatestSnapshot:
    settings = request.app.state.settings
    if not any(s.api_symbol == api_symbol for s in settings.symbols):
        raise HTTPException(
            status_code=404,
            detail={
                "error": "symbol_not_found",
                "message": f"Unknown api_symbol: {api_symbol}",
            },
        )
    snap = snap_repo.latest_for_symbol(settings.storage.db_path, api_symbol)
    if not snap:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "symbol_not_found",
                "message": f"No snapshot yet for {api_symbol}",
            },
        )
    now = datetime.now(timezone.utc)
    snap = _attach_freshness(snap, now, settings.collection.stale_threshold_seconds)
    return LatestSnapshot.model_validate(snap)


@router.get("/boards", response_model=BoardsBulkResponse)
async def bulk_boards(
    request: Request,
    symbols: Optional[str] = Query(default=None, description="comma separated"),
) -> BoardsBulkResponse:
    settings = request.app.state.settings
    if symbols:
        requested = [s.strip() for s in symbols.split(",") if s.strip()]
        configured = {s.api_symbol for s in settings.symbols}
        unknown = [s for s in requested if s not in configured]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_query",
                    "message": f"Unknown api_symbol(s): {','.join(unknown)}",
                },
            )
        target = requested
    else:
        target = [s.api_symbol for s in settings.symbols]

    snaps = snap_repo.latest_for_symbols(settings.storage.db_path, target)
    now = datetime.now(timezone.utc)
    snaps = [
        _attach_freshness(s, now, settings.collection.stale_threshold_seconds)
        for s in snaps
    ]
    return BoardsBulkResponse(
        count=len(snaps),
        snapshots=[LatestSnapshot.model_validate(s) for s in snaps],
    )
