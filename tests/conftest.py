"""Common test fixtures.

Each test gets a temp DB and an isolated FastAPI app whose collector thread is
neutered (no kabu calls). We seed snapshots directly to exercise read paths.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Mark "we're in tests" so app.main doesn't try to wire up at import time.
os.environ.setdefault("KABU_RELAY_SKIP_BOOT", "1")
# Don't write logs/relay.log from tests — leave the dev install pristine.
os.environ.setdefault("KABU_RELAY_DISABLE_FILE_LOG", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import auth as auth_mod  # noqa: E402
from app.collector import Collector  # noqa: E402
from app.db import init_schema  # noqa: E402
from app.main import build_app  # noqa: E402
from app.settings import load_settings  # noqa: E402
from app.token_manager import TokenManager  # noqa: E402


BEARER = "test-bearer-secret"
API_PASSWORD = "test-api-password"


def _write_config(tmp_path: Path, *, symbol_count: int = 3, port: int = 18091) -> Path:
    cfg = {
        "service": {"name": "kabu-relay", "version": "v1"},
        "server": {
            "listen_host": "127.0.0.1",
            "listen_port": port,
            "bearer_token_env": "KABU_RELAY_BEARER_TOKEN",
            "allowed_subnets": ["127.0.0.1/32", "::1/128"],
        },
        "kabu": {
            "host": "127.0.0.1",
            "port": 18080,
            "api_password_env": "KABU_API_PASSWORD",
            "token_refresh": {
                "on_start": False,
                "on_401_retry_once": True,
                "daily_refresh_jst": "08:55:00",
            },
        },
        "collection": {
            "mode": "poll",
            "poll_interval_seconds": 5,
            "business_days_only": True,
            "timezone": "Asia/Tokyo",
            "sessions": [
                {"name": "morning", "start": "09:00:00", "end": "11:30:00"},
                {"name": "afternoon", "start": "12:30:00", "end": "15:30:00"},
            ],
            "stale_threshold_seconds": 60,
        },
        "storage": {
            "db_path": str(tmp_path / "data" / "test.db"),
            "export_dir": str(tmp_path / "exports"),
            "keep_exports": 3,
        },
        "symbols": [
            {
                "api_symbol": f"{1000 + i}@3",
                "symbol": str(1000 + i),
                "exchange": 3,
                "name": f"test-{i}",
                "bucket": "tier1",
            }
            for i in range(symbol_count)
        ],
    }
    out = tmp_path / "config.json"
    out.write_text(json.dumps(cfg), encoding="utf-8")
    return out


def _seed_snapshot(db_path: str, *, api_symbol: str, run_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    bids = [{"level": 1, "price": 500.0, "qty": 100.0}]
    asks = [{"level": 1, "price": 502.0, "qty": 200.0}]
    raw = {"Symbol": api_symbol.split("@")[0], "Buy1": {"Price": 500, "Qty": 100}}
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO orderbook_snapshots (run_id, collected_at, symbol, symbol_name, bucket,"
            " exchange, api_symbol, best_bid_price, best_bid_qty, best_ask_price, best_ask_qty,"
            " mid_price, spread, spread_pct, bid_depth_5_jpy, ask_depth_5_jpy,"
            " bids_json, asks_json, trading_volume, vwap, current_price, current_price_time, raw_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 500, 100, 502, 200, 501, 2, 0.4, 50000, 100400,"
            " ?, ?, 1500, 501.2, 501, ?, ?)",
            (
                run_id,
                now,
                api_symbol.split("@")[0],
                "test",
                "tier1",
                3,
                api_symbol,
                json.dumps(bids),
                json.dumps(asks),
                now,
                json.dumps(raw),
            ),
        )


@pytest.fixture
def settings_factory(tmp_path, monkeypatch):
    def _make(symbol_count: int = 3, port: int = 18091):
        monkeypatch.setenv("KABU_RELAY_BEARER_TOKEN", BEARER)
        monkeypatch.setenv("KABU_API_PASSWORD", API_PASSWORD)
        cfg_path = _write_config(tmp_path, symbol_count=symbol_count, port=port)
        return load_settings(str(cfg_path))
    return _make


@pytest.fixture
def app_with_seeded_db(settings_factory, monkeypatch):
    """Build an app with seed data, but neuter the collector loop.

    The lifespan still runs; we override the collector's start() to skip the
    real polling thread by stubbing kabu client + token before build.
    """
    settings = settings_factory(symbol_count=3)
    init_schema(settings.storage.db_path)

    # Seed each configured symbol.
    for s in settings.symbols:
        _seed_snapshot(settings.storage.db_path, api_symbol=s.api_symbol, run_id="test-run")

    # Patch Collector.start so the lifespan doesn't spawn a real polling thread.
    monkeypatch.setattr(Collector, "start", lambda self: setattr(self.status, "running", True))
    monkeypatch.setattr(Collector, "stop", lambda self, timeout=5.0: setattr(self.status, "running", False))
    # Patch token refresh so it doesn't actually call kabu.
    monkeypatch.setattr(TokenManager, "refresh", lambda self, raise_on_fail=False: True)
    # TestClient sets client.host="testclient" by default; pretend it's 127.0.0.1.
    monkeypatch.setattr(
        auth_mod, "_client_ip",
        lambda req: "127.0.0.1" if (req.client is None or req.client.host == "testclient") else req.client.host,
    )

    app = build_app(settings)
    client = TestClient(app)
    with client:
        yield client, settings


@pytest.fixture
def app_minimal(settings_factory, monkeypatch):
    """Like the seeded fixture but no rows."""
    settings = settings_factory(symbol_count=3)
    init_schema(settings.storage.db_path)
    monkeypatch.setattr(Collector, "start", lambda self: setattr(self.status, "running", True))
    monkeypatch.setattr(Collector, "stop", lambda self, timeout=5.0: setattr(self.status, "running", False))
    monkeypatch.setattr(TokenManager, "refresh", lambda self, raise_on_fail=False: True)
    monkeypatch.setattr(
        auth_mod, "_client_ip",
        lambda req: "127.0.0.1" if (req.client is None or req.client.host == "testclient") else req.client.host,
    )
    app = build_app(settings)
    client = TestClient(app)
    with client:
        yield client, settings
