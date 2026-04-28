"""Settings/validation tests — especially the 50-symbol cap."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.settings import ConfigError, load_settings


def _base_cfg(symbol_count: int, *, listen_port: int = 18091, kabu_port: int = 18080) -> dict:
    return {
        "service": {"name": "kabu-relay", "version": "v1"},
        "server": {
            "listen_host": "127.0.0.1",
            "listen_port": listen_port,
            "bearer_token_env": "KABU_RELAY_BEARER_TOKEN",
            "allowed_subnets": ["127.0.0.1/32"],
        },
        "kabu": {
            "host": "127.0.0.1",
            "port": kabu_port,
            "api_password_env": "KABU_API_PASSWORD",
        },
        "collection": {
            "mode": "poll",
            "poll_interval_seconds": 5,
            "sessions": [
                {"name": "morning", "start": "09:00:00", "end": "11:30:00"},
            ],
        },
        "storage": {"db_path": "./data/test.db", "export_dir": "./exports"},
        "symbols": [
            {
                "api_symbol": f"{1000 + i}@3",
                "symbol": str(1000 + i),
                "exchange": 3,
                "name": f"s{i}",
                "bucket": "tier1",
            }
            for i in range(symbol_count)
        ],
    }


def _write(tmp_path: Path, cfg: dict) -> Path:
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


def test_loads_basic_config(tmp_path, monkeypatch):
    monkeypatch.setenv("KABU_RELAY_BEARER_TOKEN", "x")
    monkeypatch.setenv("KABU_API_PASSWORD", "y")
    p = _write(tmp_path, _base_cfg(7))
    s = load_settings(str(p))
    assert len(s.symbols) == 7
    assert s.bearer_token == "x"
    assert s.api_password == "y"


def test_rejects_more_than_50_symbols(tmp_path, monkeypatch):
    monkeypatch.setenv("KABU_RELAY_BEARER_TOKEN", "x")
    monkeypatch.setenv("KABU_API_PASSWORD", "y")
    p = _write(tmp_path, _base_cfg(51))
    with pytest.raises(ConfigError):
        load_settings(str(p))


def test_accepts_exactly_50_symbols(tmp_path, monkeypatch):
    monkeypatch.setenv("KABU_RELAY_BEARER_TOKEN", "x")
    monkeypatch.setenv("KABU_API_PASSWORD", "y")
    p = _write(tmp_path, _base_cfg(50))
    s = load_settings(str(p))
    assert len(s.symbols) == 50


def test_rejects_listen_port_eq_kabu_port(tmp_path, monkeypatch):
    monkeypatch.setenv("KABU_RELAY_BEARER_TOKEN", "x")
    monkeypatch.setenv("KABU_API_PASSWORD", "y")
    cfg = _base_cfg(3, listen_port=18080, kabu_port=18080)
    p = _write(tmp_path, cfg)
    with pytest.raises(ConfigError):
        load_settings(str(p))


def test_rejects_missing_bearer_env(tmp_path, monkeypatch):
    monkeypatch.delenv("KABU_RELAY_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("KABU_API_PASSWORD", "y")
    p = _write(tmp_path, _base_cfg(3))
    with pytest.raises(ConfigError):
        load_settings(str(p))


def test_rejects_missing_api_password_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KABU_RELAY_BEARER_TOKEN", "x")
    monkeypatch.delenv("KABU_API_PASSWORD", raising=False)
    p = _write(tmp_path, _base_cfg(3))
    with pytest.raises(ConfigError):
        load_settings(str(p))


def test_env_overrides_apply(tmp_path, monkeypatch):
    monkeypatch.setenv("KABU_RELAY_BEARER_TOKEN", "x")
    monkeypatch.setenv("KABU_API_PASSWORD", "y")
    monkeypatch.setenv("KABU_RELAY_LISTEN_PORT", "29999")
    monkeypatch.setenv("KABU_HOST", "127.0.0.2")
    p = _write(tmp_path, _base_cfg(3))
    s = load_settings(str(p))
    assert s.server.listen_port == 29999
    assert s.kabu.host == "127.0.0.2"


def test_ip_allowlist_membership(tmp_path, monkeypatch):
    monkeypatch.setenv("KABU_RELAY_BEARER_TOKEN", "x")
    monkeypatch.setenv("KABU_API_PASSWORD", "y")
    cfg = _base_cfg(3)
    cfg["server"]["allowed_subnets"] = ["192.168.0.0/24", "127.0.0.1/32"]
    p = _write(tmp_path, cfg)
    s = load_settings(str(p))
    assert s.is_ip_allowed("127.0.0.1")
    assert s.is_ip_allowed("192.168.0.42")
    assert not s.is_ip_allowed("10.0.0.1")
    assert not s.is_ip_allowed("not-an-ip")
