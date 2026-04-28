"""C-11 #2: concurrent /v1/export/sqlite/latest must not corrupt the frozen
file. The first request acquires ExportService._lock and runs to completion;
any concurrent second request gets `409 export_in_progress`.

We test this in two layers:

1. **Service layer** — verify ExportService._lock semantics directly.
   Patch `_freeze` to sleep so a second thread overlaps. Expect
   `ExportBusyError` from the second call, then a successful third call
   after the first releases.

2. **Route layer** — verify the route translates ExportBusyError into
   `HTTP 409 {"error":"export_in_progress"}` (the public contract).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth as auth_mod
from app.collector import Collector
from app.db import init_schema
from app.export_service import ExportBusyError, ExportService
from app.main import build_app
from app.token_manager import TokenManager
from app.settings import (
    CollectionSettings,
    KabuSettings,
    RelaySettings,
    ServerSettings,
    SessionWindow,
    StorageSettings,
    SymbolEntry,
)


# ----- service layer -----------------------------------------------------


def _seed_minimal_db(db_path: Path) -> None:
    init_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO orderbook_snapshots (run_id, collected_at, symbol, raw_json)"
            " VALUES (?, ?, ?, ?)",
            ("r", datetime.now(timezone.utc).isoformat(), "X", "{}"),
        )


def test_service_layer_second_concurrent_export_raises_busy(tmp_path, monkeypatch):
    db = tmp_path / "live.db"
    exports = tmp_path / "exports"
    _seed_minimal_db(db)

    svc = ExportService(db_path=str(db), export_dir=str(exports), keep=5)

    # Wrap the real freeze with a sleep at the front so two threads overlap
    # inside ExportService.create_frozen_copy(). Using the real freeze means
    # the frozen file is valid SQLite (handles WAL correctly).
    started = threading.Event()
    finish_first = threading.Event()
    real_freeze = ExportService._freeze

    def slow_freeze(self, src, dst):
        started.set()
        finish_first.wait(timeout=5)
        real_freeze(self, src, dst)

    monkeypatch.setattr(ExportService, "_freeze", slow_freeze)

    results: dict = {}

    def first_call():
        try:
            results["first"] = svc.create_frozen_copy()
        except Exception as e:  # noqa: BLE001
            results["first"] = e

    def second_call():
        # Wait until the first has the lock, then race in.
        started.wait(timeout=2)
        try:
            results["second"] = svc.create_frozen_copy()
        except Exception as e:  # noqa: BLE001
            results["second"] = e

    t1 = threading.Thread(target=first_call)
    t2 = threading.Thread(target=second_call)
    t1.start(); t2.start()

    # Let the second thread bump into the busy lock, then release the first.
    started.wait(timeout=2)
    # Give thread #2 a moment to attempt the call and bounce off.
    time.sleep(0.1)
    finish_first.set()
    t1.join(timeout=5); t2.join(timeout=5)

    assert isinstance(results["first"], dict), f"first call should succeed, got {results['first']!r}"
    assert isinstance(results["second"], ExportBusyError), (
        f"second concurrent call should raise ExportBusyError, got {results['second']!r}"
    )
    assert results["first"]["snapshot_rows"] == 1
    # Lock must be released after the first call returns — verify by inspecting
    # the lock state directly (acquiring non-blocking should now succeed).
    assert svc._lock.acquire(blocking=False), "lock should be released after first call returned"
    svc._lock.release()


# ----- route layer -------------------------------------------------------


BEARER = "test-bearer-secret"


def _route_settings(tmp_path: Path) -> RelaySettings:
    return RelaySettings(
        server=ServerSettings(
            listen_host="127.0.0.1",
            listen_port=18091,
            bearer_token_env="KABU_RELAY_BEARER_TOKEN",
            allowed_subnets=["127.0.0.1/32"],
        ),
        kabu=KabuSettings(host="localhost", port=18080, api_password_env="KABU_API_PASSWORD"),
        collection=CollectionSettings(
            poll_interval_seconds=5,
            sessions=[SessionWindow(name="morning", start="09:00:00", end="11:30:00")],
        ),
        storage=StorageSettings(db_path=str(tmp_path / "live.db"), export_dir=str(tmp_path / "exports")),
        symbols=[SymbolEntry(api_symbol="7203@1", symbol="7203", exchange=1, name="t", bucket="tier1")],
        bearer_token=BEARER,
        api_password="x",
    )


def test_route_returns_409_when_export_service_is_busy(tmp_path, monkeypatch):
    settings = _route_settings(tmp_path)
    init_schema(settings.storage.db_path)

    # Don't spawn a real collector or hit kabu during lifespan.
    monkeypatch.setattr(Collector, "start", lambda self: setattr(self.status, "running", True))
    monkeypatch.setattr(Collector, "stop", lambda self, timeout=5.0: setattr(self.status, "running", False))
    monkeypatch.setattr(TokenManager, "refresh", lambda self, raise_on_fail=False: True)
    monkeypatch.setattr(
        auth_mod, "_client_ip",
        lambda req: "127.0.0.1" if (req.client is None or req.client.host == "testclient") else req.client.host,
    )

    app = build_app(settings)

    with TestClient(app) as client:
        # Replace the real ExportService on the wired app with one that always
        # reports busy. We override AFTER lifespan ran so we replace the live
        # instance the route resolves through `request.app.state`.
        class AlwaysBusy:
            def create_frozen_copy(self_inner):
                raise ExportBusyError("under test")
            def latest_export_meta(self_inner):
                return None
        client.app.state.export_service = AlwaysBusy()

        r = client.get(
            "/v1/export/sqlite/latest",
            headers={"Authorization": f"Bearer {BEARER}"},
        )

    assert r.status_code == 409, r.text
    body = r.json()
    assert body["error"] == "export_in_progress"
    assert "another export" in body["message"].lower() or "under test" not in body["message"]
