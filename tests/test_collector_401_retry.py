"""C-11 #1: collector survives a 401 from kabu by refreshing the token once
and retrying the same board fetch. Reflects the real-machine behavior
observed during Gate A: kabu's test environment cycled tokens roughly
every minute, the relay logged

    got 401 for 7203@1; refreshing token once and retrying

and the next cycle ended `fetched=3 errors=0`.

Pinning that behavior here so we don't regress.

Coverage:
- fetch_board called twice (initial 401 + retry 200)
- token_mgr.refresh() called once
- snapshot row inserted
- consecutive_error_count stays at 0
- kabu_reachable stays True (no error storm)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.collector import Collector
from app.db import init_schema
from app.kabu_client import KabuApiError, KabuClient, KabuUnauthorizedError
from app.settings import (
    CollectionSettings,
    KabuSettings,
    RelaySettings,
    ServerSettings,
    SessionWindow,
    StorageSettings,
    SymbolEntry,
)
from app.token_manager import TokenManager


# Minimal but realistic kabu board, matching what was captured during Gate A.
GOOD_BOARD = {
    "Symbol": "7203",
    "SymbolName": "トヨタ自動車",
    "CurrentPrice": 3121.0,
    "CurrentPriceTime": "2026-04-28T15:24:59+09:00",
    "TradingVolume": 13_126_600.0,
    "VWAP": 3108.4709,
    "Buy1":  {"Price": 3120.0, "Qty": 6600.0},
    "Buy2":  {"Price": 3119.0, "Qty": 16700.0},
    "Buy3":  {"Price": 3118.0, "Qty": 24400.0},
    "Buy4":  {"Price": 3117.0, "Qty": 19500.0},
    "Buy5":  {"Price": 3116.0, "Qty": 32200.0},
    "Buy6":  {"Price": 3115.0, "Qty": 24800.0},
    "Buy7":  {"Price": 3114.0, "Qty": 18300.0},
    "Buy8":  {"Price": 3113.0, "Qty": 16500.0},
    "Buy9":  {"Price": 3112.0, "Qty": 17800.0},
    "Buy10": {"Price": 3111.0, "Qty": 20400.0},
    "Sell1": {"Price": 3121.0, "Qty": 8100.0},
    "Sell2": {"Price": 3122.0, "Qty": 14900.0},
    "Sell3": {"Price": 3123.0, "Qty": 23400.0},
    "Sell4": {"Price": 3124.0, "Qty": 19200.0},
    "Sell5": {"Price": 3125.0, "Qty": 27000.0},
    "Sell6": {"Price": 3126.0, "Qty": 14400.0},
    "Sell7": {"Price": 3127.0, "Qty": 19500.0},
    "Sell8": {"Price": 3128.0, "Qty": 18100.0},
    "Sell9": {"Price": 3129.0, "Qty": 37400.0},
    "Sell10":{"Price": 3130.0, "Qty": 48700.0},
}


class _FakeClient(KabuClient):
    """KabuClient stand-in that lets the test script board responses per call."""

    def __init__(self, host="localhost", port=18080, api_password="x"):
        super().__init__(host=host, port=port, api_password=api_password)
        self.fetch_board_calls: list[tuple[str, str]] = []
        # Pre-populated script: each entry is either a dict (return) or an
        # exception class instance (raise). FIFO.
        self._board_script: list = []
        self.fetch_token_calls = 0

    def script(self, *items) -> None:
        self._board_script = list(items)

    # Override network calls.
    def fetch_token(self) -> str:
        self.fetch_token_calls += 1
        return f"fake-token-{self.fetch_token_calls}"

    def fetch_board(self, api_symbol: str, token: str) -> dict:
        self.fetch_board_calls.append((api_symbol, token))
        if not self._board_script:
            raise AssertionError("fetch_board called more times than scripted")
        item = self._board_script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _settings(tmp_path: Path) -> RelaySettings:
    db = tmp_path / "test.db"
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
        storage=StorageSettings(db_path=str(db), export_dir=str(tmp_path / "exports")),
        symbols=[
            SymbolEntry(api_symbol="7203@1", symbol="7203", exchange=1, name="トヨタ自動車", bucket="tier1"),
        ],
    )


def test_collector_recovers_from_401_with_one_refresh_and_one_retry(tmp_path):
    settings = _settings(tmp_path)
    init_schema(settings.storage.db_path)

    client = _FakeClient()
    # First call raises 401, second returns valid board.
    client.script(KabuUnauthorizedError("board 7203@1 returned 401", status=401), GOOD_BOARD)

    token_mgr = TokenManager(client)
    # Pre-load a stale token so first board fetch happens.
    assert token_mgr.refresh() is True
    initial_refresh_calls = client.fetch_token_calls   # = 1

    collector = Collector(settings, client, token_mgr)
    # Establish a collector_runs row so snapshot inserts have a valid run_id ref
    # (not strictly required by our schema FK, but matches the production path).
    with sqlite3.connect(settings.storage.db_path) as conn:
        conn.execute(
            "INSERT INTO collector_runs (run_id, started_at, config_path, db_path, status)"
            " VALUES (?, ?, '', ?, 'running')",
            (collector.run_id, datetime.now(timezone.utc).isoformat(), settings.storage.db_path),
        )

    # Run exactly one cycle.
    collector._cycle(datetime.now(timezone.utc))

    # 1. fetch_board attempted twice (initial + 1 retry).
    assert len(client.fetch_board_calls) == 2, client.fetch_board_calls
    # 2. token_mgr.refresh ran exactly once during the cycle (= 1 over the
    #    initial pre-load).
    cycle_refreshes = client.fetch_token_calls - initial_refresh_calls
    assert cycle_refreshes == 1, f"expected 1 refresh during cycle, got {cycle_refreshes}"
    # 3. The retry used the new token.
    first_token = client.fetch_board_calls[0][1]
    second_token = client.fetch_board_calls[1][1]
    assert first_token != second_token, "retry should have used a freshly-refreshed token"
    # 4. snapshot landed in the DB.
    with sqlite3.connect(settings.storage.db_path) as conn:
        n = conn.execute("SELECT COUNT(1) FROM orderbook_snapshots").fetchone()[0]
    assert n == 1, f"expected 1 snapshot row, got {n}"
    # 5. status reflects success, not error storm.
    snap = collector.status.snapshot()
    assert snap["consecutive_error_count"] == 0
    assert snap["kabu_reachable"] is True
    assert snap["last_success_at_utc"] is not None
    assert snap["last_error_at_utc"] is None


def test_collector_does_not_loop_refresh_on_persistent_401(tmp_path):
    """If the retry ALSO returns 401, we don't refresh again; the symbol fetch
    is logged as an error and the cycle continues. This guards against an
    infinite refresh loop on a wedged token."""
    settings = _settings(tmp_path)
    init_schema(settings.storage.db_path)

    client = _FakeClient()
    # Two 401s back to back.
    client.script(
        KabuUnauthorizedError("first 401", status=401),
        KabuUnauthorizedError("second 401", status=401),
    )

    token_mgr = TokenManager(client)
    assert token_mgr.refresh() is True
    initial_refresh_calls = client.fetch_token_calls

    collector = Collector(settings, client, token_mgr)
    with sqlite3.connect(settings.storage.db_path) as conn:
        conn.execute(
            "INSERT INTO collector_runs (run_id, started_at, config_path, db_path, status)"
            " VALUES (?, ?, '', ?, 'running')",
            (collector.run_id, datetime.now(timezone.utc).isoformat(), settings.storage.db_path),
        )

    collector._cycle(datetime.now(timezone.utc))

    # Exactly one refresh during the retry attempt — not a refresh per failure.
    cycle_refreshes = client.fetch_token_calls - initial_refresh_calls
    assert cycle_refreshes == 1
    # No snapshot recorded (both attempts failed).
    with sqlite3.connect(settings.storage.db_path) as conn:
        n = conn.execute("SELECT COUNT(1) FROM orderbook_snapshots").fetchone()[0]
    assert n == 0
    # Error counter advanced exactly once for this single symbol.
    snap = collector.status.snapshot()
    assert snap["consecutive_error_count"] == 1
    assert snap["last_error_message"] is not None and "7203@1" in snap["last_error_message"]
