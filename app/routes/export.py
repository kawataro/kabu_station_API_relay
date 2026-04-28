from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ..export_service import ExportBusyError
from ..models import ExportMeta, ExportMetaResponse


router = APIRouter(prefix="/v1")


@router.get("/export/meta", response_model=ExportMetaResponse)
async def export_meta(request: Request) -> ExportMetaResponse:
    svc = request.app.state.export_service
    meta = svc.latest_export_meta()
    if not meta:
        return ExportMetaResponse(latest_export=None)
    return ExportMetaResponse(latest_export=ExportMeta(**{
        "created_at_utc": meta["created_at_utc"],
        "file_name": meta["file_name"],
        "file_size_bytes": meta["file_size_bytes"],
        "snapshot_rows": meta["snapshot_rows"],
        "price_change_rows": meta["price_change_rows"],
        "latest_snapshot_at_utc": meta["latest_snapshot_at_utc"],
    }))


@router.get("/export/sqlite/latest")
async def export_sqlite_latest(request: Request):
    svc = request.app.state.export_service
    try:
        meta = svc.create_frozen_copy()
    except ExportBusyError:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "export_in_progress",
                "message": "another export is already running",
            },
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={
                "error": "internal_error",
                "message": f"export failed: {e}",
            },
        ) from e
    file_path = Path(meta["file_path"])
    return FileResponse(
        path=str(file_path),
        media_type="application/octet-stream",
        filename=meta["file_name"],
    )
