"""Config + env loader with hard validation.

Hard rules enforced here:
- `symbols.length <= 50` (kabu's combined REST/PUSH registration cap).
- `poll_interval_seconds > 0`.
- `server.listen_port != kabu.port`.
- bearer token & APIPassword resolved from env (never config).
"""

from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


MAX_SYMBOLS = 50


class ConfigError(RuntimeError):
    pass


class ServiceInfo(BaseModel):
    name: str = "kabu-relay"
    version: str = "v1"


class ServerSettings(BaseModel):
    listen_host: str
    listen_port: int
    bearer_token_env: str
    allowed_subnets: list[str]

    @field_validator("allowed_subnets")
    @classmethod
    def _check_subnets(cls, v: list[str]) -> list[str]:
        for s in v:
            ipaddress.ip_network(s, strict=False)
        return v


class TokenRefreshSettings(BaseModel):
    on_start: bool = True
    on_401_retry_once: bool = True
    daily_refresh_jst: str = "08:55:00"


class KabuSettings(BaseModel):
    host: str
    port: int
    api_password_env: str
    token_refresh: TokenRefreshSettings = Field(default_factory=TokenRefreshSettings)


class SessionWindow(BaseModel):
    name: str
    start: str  # "HH:MM:SS"
    end: str


class CollectionSettings(BaseModel):
    mode: str = "poll"
    poll_interval_seconds: float = 5.0
    business_days_only: bool = True
    timezone: str = "Asia/Tokyo"
    sessions: list[SessionWindow]
    stale_threshold_seconds: float = 60.0
    # Override-list of "YYYY-MM-DD" strings (JST) treated as market closed in
    # addition to weekends and Japanese national holidays. Useful for
    # year-end / new-year market closures (12/31, 1/2, 1/3) and ad-hoc days.
    extra_closed_dates: list[str] = []

    @field_validator("poll_interval_seconds")
    @classmethod
    def _positive_interval(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("poll_interval_seconds must be > 0")
        return v


class StorageSettings(BaseModel):
    db_path: str
    export_dir: str
    keep_exports: int = 10


class SymbolEntry(BaseModel):
    api_symbol: str
    symbol: str
    exchange: int
    name: str
    bucket: str


class RelaySettings(BaseModel):
    service: ServiceInfo = Field(default_factory=ServiceInfo)
    server: ServerSettings
    kabu: KabuSettings
    collection: CollectionSettings
    storage: StorageSettings
    symbols: list[SymbolEntry]

    # Resolved secrets (not present in JSON; injected from env).
    bearer_token: str = Field(default="", repr=False)
    api_password: str = Field(default="", repr=False)
    config_path: str = ""

    @field_validator("symbols")
    @classmethod
    def _cap_symbols(cls, v: list[SymbolEntry]) -> list[SymbolEntry]:
        if len(v) > MAX_SYMBOLS:
            raise ValueError(
                f"configured symbols={len(v)} exceeds kabu's combined REST/PUSH cap of {MAX_SYMBOLS}"
            )
        return v

    def cross_validate(self) -> None:
        if self.server.listen_port == self.kabu.port:
            raise ConfigError(
                f"server.listen_port ({self.server.listen_port}) must differ from kabu.port"
            )
        seen: set[str] = set()
        for s in self.symbols:
            if s.api_symbol in seen:
                raise ConfigError(f"duplicate api_symbol: {s.api_symbol}")
            seen.add(s.api_symbol)

    def is_ip_allowed(self, addr: str) -> bool:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        for net in self.server.allowed_subnets:
            if ip in ipaddress.ip_network(net, strict=False):
                return True
        return False


def _apply_env_overrides(raw: dict, env: dict[str, str]) -> dict:
    server = raw.setdefault("server", {})
    if "KABU_RELAY_LISTEN_HOST" in env:
        server["listen_host"] = env["KABU_RELAY_LISTEN_HOST"]
    if "KABU_RELAY_LISTEN_PORT" in env:
        server["listen_port"] = int(env["KABU_RELAY_LISTEN_PORT"])

    kabu = raw.setdefault("kabu", {})
    if "KABU_HOST" in env:
        kabu["host"] = env["KABU_HOST"]
    if "KABU_PORT" in env:
        kabu["port"] = int(env["KABU_PORT"])

    storage = raw.setdefault("storage", {})
    if "KABU_DB_PATH" in env:
        storage["db_path"] = env["KABU_DB_PATH"]
    if "KABU_EXPORT_DIR" in env:
        storage["export_dir"] = env["KABU_EXPORT_DIR"]

    return raw


def load_settings(
    config_path: str | None = None,
    env: dict[str, str] | None = None,
    *,
    require_secrets: bool = True,
) -> RelaySettings:
    env = env if env is not None else dict(os.environ)
    cfg_path = config_path or env.get("KABU_RELAY_CONFIG", "./config/relay_config.json")
    cfg_file = Path(cfg_path)
    if not cfg_file.exists():
        raise ConfigError(f"config file not found: {cfg_file}")
    with cfg_file.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    raw = _apply_env_overrides(raw, env)

    try:
        s = RelaySettings.model_validate(raw)
    except Exception as e:  # noqa: BLE001
        raise ConfigError(f"invalid config: {e}") from e
    s.config_path = str(cfg_file.resolve())
    s.cross_validate()

    bearer = env.get(s.server.bearer_token_env, "")
    api_pw = env.get(s.kabu.api_password_env, "")
    if require_secrets:
        if not bearer:
            raise ConfigError(
                f"missing bearer token: env {s.server.bearer_token_env} is unset/empty"
            )
        if not api_pw:
            raise ConfigError(
                f"missing kabu APIPassword: env {s.kabu.api_password_env} is unset/empty"
            )
    s.bearer_token = bearer
    s.api_password = api_pw
    return s
