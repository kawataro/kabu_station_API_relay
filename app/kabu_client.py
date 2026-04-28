"""Thin HTTP client for the local kabuステーションAPI.

Only observation endpoints are exposed:
- POST /kabusapi/token       (fetch a session token from APIPassword)
- GET  /kabusapi/board/{sym} (read latest board for a symbol)
- PUT  /kabusapi/register    (optional explicit registration; not used by MVP)

No order/cancel/modify methods exist here by design.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import requests


log = logging.getLogger(__name__)


class KabuApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class KabuUnauthorizedError(KabuApiError):
    """401 from kabu — token likely expired."""


@dataclass
class KabuClient:
    host: str
    port: int
    api_password: str
    timeout: float = 5.0

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def fetch_token(self) -> str:
        url = f"{self.base_url}/kabusapi/token"
        try:
            r = requests.post(
                url,
                json={"APIPassword": self.api_password},
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise KabuApiError(f"token request failed: {e}") from e
        if r.status_code != 200:
            # Never log the body verbatim — kabu echoes APIPassword on some errors.
            raise KabuApiError(
                f"token request returned HTTP {r.status_code}",
                status=r.status_code,
            )
        try:
            data = r.json()
        except ValueError as e:
            raise KabuApiError("token response was not JSON") from e
        token = data.get("Token")
        if not token:
            raise KabuApiError("token response missing 'Token' field")
        return token

    def fetch_board(self, api_symbol: str, token: str) -> dict[str, Any]:
        url = f"{self.base_url}/kabusapi/board/{api_symbol}"
        try:
            r = requests.get(
                url,
                headers={"X-API-KEY": token},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise KabuApiError(f"board request failed for {api_symbol}: {e}") from e
        if r.status_code == 401:
            raise KabuUnauthorizedError(f"board {api_symbol} returned 401", status=401)
        if r.status_code != 200:
            raise KabuApiError(
                f"board {api_symbol} returned HTTP {r.status_code}",
                status=r.status_code,
            )
        try:
            return r.json()
        except ValueError as e:
            raise KabuApiError(f"board {api_symbol} response was not JSON") from e

    def register_symbols(
        self, symbols: list[dict[str, Any]], token: str
    ) -> dict[str, Any]:
        """Optional explicit registration; deterministic universe pinning.

        Body shape per kabu docs:
            { "Symbols": [ {"Symbol": "4582", "Exchange": 3}, ... ] }
        Not required for board-poll MVP because /board auto-registers, but
        kept here for callers that want deterministic behavior.
        """
        url = f"{self.base_url}/kabusapi/register"
        body = {"Symbols": symbols}
        try:
            r = requests.put(
                url,
                data=json.dumps(body),
                headers={"Content-Type": "application/json", "X-API-KEY": token},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise KabuApiError(f"register request failed: {e}") from e
        if r.status_code == 401:
            raise KabuUnauthorizedError("register returned 401", status=401)
        if r.status_code != 200:
            raise KabuApiError(
                f"register returned HTTP {r.status_code}", status=r.status_code
            )
        try:
            return r.json()
        except ValueError:
            return {}
