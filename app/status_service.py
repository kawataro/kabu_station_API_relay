"""Aggregates state for /v1/status."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .collector import Collector, staleness_label
from .repositories import snapshots as snap_repo, price_changes as pc_repo
from .settings import RelaySettings
from .token_manager import TokenManager


def build_status(
    settings: RelaySettings,
    token_mgr: TokenManager,
    collector: Collector,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    coll = collector.status.snapshot()

    latest_snapshot_at = snap_repo.latest_collected_at(settings.storage.db_path)
    snap_rows = snap_repo.total_row_count(settings.storage.db_path)
    pc_rows = pc_repo.total_row_count(settings.storage.db_path)

    lag_seconds = None
    if latest_snapshot_at:
        try:
            t = datetime.fromisoformat(latest_snapshot_at)
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            lag_seconds = (now - t).total_seconds()
        except ValueError:
            lag_seconds = None

    fresh = staleness_label(latest_snapshot_at, now)

    token_state = token_mgr.public_state()

    return {
        "ok": True,
        "service": settings.service.name,
        "version": settings.service.version,
        "server_time_utc": now.isoformat(),
        "collector": {
            "running": coll["running"],
            "mode": coll["mode"],
            "poll_interval_seconds": coll["poll_interval_seconds"],
            "configured_symbol_count": coll["configured_symbol_count"],
            "last_success_at_utc": coll["last_success_at_utc"],
            "last_error_at_utc": coll["last_error_at_utc"],
            "last_error_message": coll["last_error_message"],
            "consecutive_error_count": coll["consecutive_error_count"],
            "lag_seconds": lag_seconds,
            "last_cycle_duration_seconds": coll["last_cycle_duration_seconds"],
            "market_session": coll["market_session"],
            "market_open": coll["market_open"],
            "freshness": fresh,
        },
        "kabu": {
            "reachable": coll["kabu_reachable"],
            "host": settings.kabu.host,
            "port": settings.kabu.port,
            "token_status": token_state["token_status"],
            "token_last_refreshed_at_utc": token_state["token_last_refreshed_at_utc"],
        },
        "storage": {
            "db_path": settings.storage.db_path,
            "latest_snapshot_at_utc": latest_snapshot_at,
            "snapshot_rows": snap_rows,
            "price_change_rows": pc_rows,
        },
    }
