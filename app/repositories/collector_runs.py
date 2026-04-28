"""collector_runs queries."""

from __future__ import annotations

from typing import Any, Optional

from ..db import connect


def latest_run(db_path: str) -> Optional[dict[str, Any]]:
    with connect(db_path, read_only=True) as conn:
        cur = conn.execute(
            "SELECT run_id, started_at, config_path, db_path, status, notes"
            " FROM collector_runs ORDER BY started_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "run_id": row["run_id"],
        "started_at": row["started_at"],
        "config_path": row["config_path"],
        "db_path": row["db_path"],
        "status": row["status"],
        "notes": row["notes"],
    }
