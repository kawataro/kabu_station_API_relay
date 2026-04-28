"""C-11 #3: KABU_RELAY_ALLOW_DEGRADED behavior.

Default policy: if `kabu.token_refresh.on_start=true` and the initial token
fetch fails, lifespan raises RuntimeError → uvicorn refuses to come up.
This is the safe default: failing fast prevents an apparently-up relay
from serving stale-empty data.

Override: setting `KABU_RELAY_ALLOW_DEGRADED=1` lets the process keep
running. `/health` still answers 200 and `/v1/status` exposes the
degraded token state so monitoring can pick it up.

Both branches are pinned here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth as auth_mod
from app.collector import Collector
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
    TokenRefreshSettings,
)


BEARER = "test-bearer-secret"


def _settings_with_on_start_true(tmp_path: Path) -> RelaySettings:
    """Settings that explicitly enable startup token refresh — the
    fail-fast vs degraded branch only triggers when `on_start=True`.
    """
    return RelaySettings(
        server=ServerSettings(
            listen_host="127.0.0.1",
            listen_port=18091,
            bearer_token_env="KABU_RELAY_BEARER_TOKEN",
            allowed_subnets=["127.0.0.1/32"],
        ),
        kabu=KabuSettings(
            host="localhost",
            port=18080,
            api_password_env="KABU_API_PASSWORD",
            token_refresh=TokenRefreshSettings(on_start=True),
        ),
        collection=CollectionSettings(
            poll_interval_seconds=5,
            sessions=[SessionWindow(name="morning", start="09:00:00", end="11:30:00")],
        ),
        storage=StorageSettings(db_path=str(tmp_path / "live.db"), export_dir=str(tmp_path / "exports")),
        symbols=[SymbolEntry(api_symbol="7203@1", symbol="7203", exchange=1, name="t", bucket="tier1")],
        bearer_token=BEARER,
        api_password="x",
    )


def _stub_collector_and_auth(monkeypatch):
    monkeypatch.setattr(Collector, "start", lambda self: setattr(self.status, "running", True))
    monkeypatch.setattr(Collector, "stop", lambda self, timeout=5.0: setattr(self.status, "running", False))
    monkeypatch.setattr(
        auth_mod, "_client_ip",
        lambda req: "127.0.0.1" if (req.client is None or req.client.host == "testclient") else req.client.host,
    )


def test_default_fail_fast_when_initial_token_fetch_fails(tmp_path, monkeypatch):
    settings = _settings_with_on_start_true(tmp_path)
    _stub_collector_and_auth(monkeypatch)

    # Make the initial token fetch fail.
    monkeypatch.setattr(TokenManager, "refresh", lambda self, raise_on_fail=False: False)
    # Ensure the override flag is NOT set.
    monkeypatch.delenv("KABU_RELAY_ALLOW_DEGRADED", raising=False)

    app = build_app(settings)

    # Lifespan runs on TestClient context entry. With on_start=True, refresh=False,
    # and ALLOW_DEGRADED unset, lifespan must raise RuntimeError.
    with pytest.raises(RuntimeError, match="initial kabu token fetch failed"):
        with TestClient(app):
            pass  # should never get here


@pytest.mark.parametrize("flag_value", ["1", "true", "yes"])
def test_degraded_boot_continues_when_flag_is_set(tmp_path, monkeypatch, flag_value):
    settings = _settings_with_on_start_true(tmp_path)
    _stub_collector_and_auth(monkeypatch)

    # Initial token fetch fails AND we set the override.
    refresh_calls = []

    def failing_refresh(self, raise_on_fail=False):
        refresh_calls.append(1)
        # Mirror what the real TokenManager.refresh does on failure: status -> degraded.
        self.state.status = "degraded"
        self.state.last_refresh_error = "stub: kabu unreachable"
        return False

    monkeypatch.setattr(TokenManager, "refresh", failing_refresh)
    monkeypatch.setenv("KABU_RELAY_ALLOW_DEGRADED", flag_value)

    app = build_app(settings)

    with TestClient(app) as client:
        # /health is exempt from auth and must answer even when degraded.
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # /v1/status with bearer must respond and surface degraded state.
        r = client.get("/v1/status", headers={"Authorization": f"Bearer {BEARER}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True  # the relay-as-a-service is up
        assert body["kabu"]["token_status"] == "degraded"
        # The collector was stubbed to "running"; that's intentional for this
        # test (we're isolating the boot decision, not the collector loop).
        assert body["collector"]["running"] is True

    # We should have attempted at least one refresh during lifespan.
    assert len(refresh_calls) >= 1


def test_on_start_false_skips_initial_fetch_entirely(tmp_path, monkeypatch):
    """Sanity branch: if `on_start=false`, the initial-fetch decision is
    bypassed entirely and the relay starts cleanly even without DEGRADED."""
    settings = _settings_with_on_start_true(tmp_path)
    settings.kabu.token_refresh.on_start = False
    _stub_collector_and_auth(monkeypatch)

    refresh_calls = []
    monkeypatch.setattr(
        TokenManager, "refresh",
        lambda self, raise_on_fail=False: (refresh_calls.append(1), False)[1],
    )
    monkeypatch.delenv("KABU_RELAY_ALLOW_DEGRADED", raising=False)

    app = build_app(settings)
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200

    # No initial refresh was attempted (on_start was False).
    assert refresh_calls == [], f"expected zero refresh calls, got {len(refresh_calls)}"
