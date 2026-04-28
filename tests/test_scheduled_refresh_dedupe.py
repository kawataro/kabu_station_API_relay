"""C-11 #4: the JST 08:55 daily refresh fires at most once per business day.

`Collector._maybe_scheduled_token_refresh` is called every poll iteration
(every ~5s). Without dedupe, every iteration inside the ±window would
trigger a refresh, hammering kabu's /token endpoint. The TokenManager
holds `last_scheduled_refresh_date_jst` to keep the firing to once per
JST date. This test pins that contract using the existing seam:
`Collector._maybe_scheduled_token_refresh(now_utc)` accepts the time
explicitly, so we don't need to monkeypatch the system clock.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.collector import Collector
from app.kabu_client import KabuClient
from app.settings import (
    CollectionSettings,
    KabuSettings,
    RelaySettings,
    ServerSettings,
    SessionWindow,
    StorageSettings,
    SymbolEntry,
    TokenRefreshSettings,
)
from app.token_manager import TokenManager


JST = ZoneInfo("Asia/Tokyo")
UTC = timezone.utc


def _settings(tmp_path: Path) -> RelaySettings:
    return RelaySettings(
        server=ServerSettings(
            listen_host="127.0.0.1",
            listen_port=18091,
            bearer_token_env="KABU_RELAY_BEARER_TOKEN",
            allowed_subnets=["127.0.0.1/32"],
        ),
        kabu=KabuSettings(
            host="localhost", port=18080, api_password_env="KABU_API_PASSWORD",
            token_refresh=TokenRefreshSettings(
                on_start=True, on_401_retry_once=True, daily_refresh_jst="08:55:00",
            ),
        ),
        collection=CollectionSettings(
            poll_interval_seconds=5,
            sessions=[SessionWindow(name="morning", start="09:00:00", end="11:30:00")],
        ),
        storage=StorageSettings(db_path=str(tmp_path / "live.db"), export_dir=str(tmp_path / "exports")),
        symbols=[SymbolEntry(api_symbol="7203@1", symbol="7203", exchange=1, name="t", bucket="tier1")],
    )


def _build_collector(tmp_path) -> tuple[Collector, list[datetime]]:
    settings = _settings(tmp_path)
    client = KabuClient(host="localhost", port=18080, api_password="x")
    token_mgr = TokenManager(client)

    refresh_calls: list[datetime] = []

    def fake_refresh(raise_on_fail: bool = False) -> bool:
        refresh_calls.append(datetime.now(UTC))
        return True

    # Bind the fake to the instance so we don't pollute the class.
    token_mgr.refresh = fake_refresh  # type: ignore[assignment]

    return Collector(settings, client, token_mgr), refresh_calls


def _utc(jst_dt: datetime) -> datetime:
    return jst_dt.astimezone(UTC)


def test_repeated_calls_inside_window_only_refresh_once_per_day(tmp_path):
    collector, calls = _build_collector(tmp_path)

    day1 = datetime(2026, 4, 28, 8, 55, 0, tzinfo=JST)  # exact target
    # Five ticks across the window on the same JST date.
    ticks = [
        day1,
        day1.replace(minute=55, second=15),
        day1.replace(minute=56, second=30),
        day1.replace(minute=58, second=0),
        day1.replace(hour=9, minute=4, second=59),  # 09:04:59 JST = +599s, still inside ≤600
    ]
    for t in ticks:
        collector._maybe_scheduled_token_refresh(_utc(t))

    assert len(calls) == 1, f"expected 1 refresh on day1, got {len(calls)}"

    # Roll forward to the next business day.
    day2 = datetime(2026, 4, 30, 8, 55, 0, tzinfo=JST)  # Thu (4/29 is 昭和の日)
    for _ in range(3):
        collector._maybe_scheduled_token_refresh(_utc(day2))

    assert len(calls) == 2, f"expected 2 refreshes total after day2, got {len(calls)}"

    # And the next day after that — date-keyed dedupe should keep working.
    day3 = datetime(2026, 5, 1, 8, 55, 30, tzinfo=JST)  # Fri
    collector._maybe_scheduled_token_refresh(_utc(day3))
    collector._maybe_scheduled_token_refresh(_utc(day3))
    assert len(calls) == 3


def test_outside_window_does_not_refresh(tmp_path):
    """Below -300s or above +600s relative to 08:55 must not fire."""
    collector, calls = _build_collector(tmp_path)

    base = datetime(2026, 4, 28, tzinfo=JST)
    too_early = base.replace(hour=8, minute=49, second=59)   # -301s
    too_late  = base.replace(hour=9, minute=5, second=1)     # +601s
    for t in (too_early, too_late):
        collector._maybe_scheduled_token_refresh(_utc(t))

    assert calls == [], f"expected no refresh outside window, got {len(calls)}"

    # Sanity: a tick inside the window now SHOULD fire.
    inside = base.replace(hour=8, minute=55)
    collector._maybe_scheduled_token_refresh(_utc(inside))
    assert len(calls) == 1


def test_refresh_disabled_when_daily_refresh_jst_is_empty(tmp_path):
    """If `daily_refresh_jst` is empty, the scheduled-refresh path is a
    pure no-op (the manual 401-retry path is the only refresh trigger)."""
    collector, calls = _build_collector(tmp_path)
    collector.settings.kabu.token_refresh.daily_refresh_jst = ""

    for h in (8, 9, 10):
        t = datetime(2026, 4, 28, h, 55, 0, tzinfo=JST)
        collector._maybe_scheduled_token_refresh(_utc(t))

    assert calls == []


def test_dedupe_state_lives_on_token_manager_not_collector(tmp_path):
    """If the collector is restarted on the same JST day, the new collector
    asks the same token_mgr whether today's refresh has already happened.
    Pinning here so that future refactors don't accidentally move dedupe
    state into Collector (where it would reset on every process restart).
    """
    collector, calls = _build_collector(tmp_path)
    t = datetime(2026, 4, 28, 8, 55, tzinfo=JST)
    collector._maybe_scheduled_token_refresh(_utc(t))
    assert len(calls) == 1

    # Build a NEW collector that shares the same token_mgr.
    same_token_mgr = collector.token_mgr
    settings = _settings(tmp_path)
    client = KabuClient(host="localhost", port=18080, api_password="x")
    second = Collector(settings, client, same_token_mgr)
    second._maybe_scheduled_token_refresh(_utc(t.replace(minute=58)))

    # Still 1, because the dedupe key is on token_mgr's state.
    assert len(calls) == 1, f"new collector with same token_mgr should not re-fire same-day, got {len(calls)}"
