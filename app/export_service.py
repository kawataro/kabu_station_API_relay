"""Frozen SQLite export.

Rules:
- never hand the live DB file directly to a client.
- use `VACUUM INTO` when supported; fall back to a defensive file copy.
- record a row in `exports` and prune older files past `keep_exports`.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .db import connect


log = logging.getLogger(__name__)


def _utc_stamp() -> str:
    # YYYYMMDDTHHMMSSZ form for filenames.
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class ExportBusyError(RuntimeError):
    pass


class ExportService:
    def __init__(self, db_path: str, export_dir: str, keep: int = 10):
        self.db_path = Path(db_path)
        self.export_dir = Path(export_dir)
        self.keep = keep
        self._lock = threading.Lock()

    # -------------------- public API --------------------

    def create_frozen_copy(self) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            raise ExportBusyError("another export is already running")
        try:
            self.export_dir.mkdir(parents=True, exist_ok=True)
            stamp = _utc_stamp()
            file_name = f"kabu_orderbook_snapshot_{stamp}.db"
            target = self.export_dir / file_name
            self._freeze(self.db_path, target)
            meta = self._record_meta(target)
            self._prune_old()
            return meta
        finally:
            self._lock.release()

    def latest_export_meta(self) -> Optional[dict[str, Any]]:
        try:
            with connect(self.db_path, read_only=True) as conn:
                row = conn.execute(
                    "SELECT created_at, file_path, file_size_bytes,"
                    " snapshot_rows, price_change_rows, latest_snapshot_at"
                    " FROM exports ORDER BY id DESC LIMIT 1"
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        if not row:
            return None
        path = Path(row["file_path"])
        return {
            "created_at_utc": row["created_at"],
            "file_name": path.name,
            "file_path": str(path),
            "file_size_bytes": int(row["file_size_bytes"] or 0),
            "snapshot_rows": int(row["snapshot_rows"] or 0),
            "price_change_rows": int(row["price_change_rows"] or 0),
            "latest_snapshot_at_utc": row["latest_snapshot_at"],
        }

    # -------------------- internals --------------------

    def _freeze(self, src: Path, dst: Path) -> None:
        """Copy live DB to dst safely.

        Try VACUUM INTO first (atomic, defragmented). If that fails (e.g.
        because dst already exists), fall back to a backup-API copy.
        """
        if dst.exists():
            dst.unlink()
        try:
            with connect(src, read_only=True) as conn:
                conn.execute("VACUUM INTO ?", (str(dst),))
            log.info("frozen export via VACUUM INTO -> %s", dst)
            return
        except sqlite3.Error as e:
            log.warning("VACUUM INTO failed (%s); falling back to backup API", e)

        # Backup API fallback. Open src RW (so SQLite can lock pages), use
        # the .backup() method to copy to a fresh DB. Never expose this
        # connection externally.
        with sqlite3.connect(str(src), timeout=30.0) as src_conn, sqlite3.connect(
            str(dst), timeout=30.0
        ) as dst_conn:
            src_conn.backup(dst_conn)
        log.info("frozen export via backup API -> %s", dst)

    def _record_meta(self, file_path: Path) -> dict[str, Any]:
        # Count rows in the frozen copy itself (avoids racing the live writer).
        with connect(file_path, read_only=True) as conn:
            snapshot_rows = conn.execute(
                "SELECT COUNT(1) AS c FROM orderbook_snapshots"
            ).fetchone()["c"]
            price_change_rows = conn.execute(
                "SELECT COUNT(1) AS c FROM price_changes"
            ).fetchone()["c"]
            latest_row = conn.execute(
                "SELECT MAX(collected_at) AS t FROM orderbook_snapshots"
            ).fetchone()
            latest_snapshot_at = latest_row["t"] if latest_row else None

        size = file_path.stat().st_size
        created_at = datetime.now(timezone.utc).isoformat()

        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO exports (created_at, file_path, file_size_bytes,"
                " snapshot_rows, price_change_rows, latest_snapshot_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    created_at,
                    str(file_path),
                    int(size),
                    int(snapshot_rows),
                    int(price_change_rows),
                    latest_snapshot_at,
                ),
            )
        return {
            "created_at_utc": created_at,
            "file_name": file_path.name,
            "file_path": str(file_path),
            "file_size_bytes": int(size),
            "snapshot_rows": int(snapshot_rows),
            "price_change_rows": int(price_change_rows),
            "latest_snapshot_at_utc": latest_snapshot_at,
        }

    def _prune_old(self) -> None:
        if self.keep <= 0:
            return
        files = sorted(
            [p for p in self.export_dir.glob("kabu_orderbook_snapshot_*.db") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in files[self.keep:]:
            try:
                old.unlink()
                log.info("pruned old export %s", old.name)
            except OSError:
                log.warning("could not prune %s", old)
