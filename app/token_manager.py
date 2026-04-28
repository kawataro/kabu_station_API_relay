"""kabu API token state holder.

Rules from spec:
- token must be acquired at startup (fail-fast if not).
- on a 401 from a downstream call, refresh exactly once and retry.
- once per business day around JST 08:55 the collector requests a refresh.
- token never leaves memory: not in API responses, not in DB, not in logs.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .kabu_client import KabuApiError, KabuClient


log = logging.getLogger(__name__)


@dataclass
class TokenState:
    status: str = "uninitialized"   # uninitialized | valid | degraded
    last_refreshed_at_utc: Optional[str] = None
    last_refresh_error: Optional[str] = None
    # Tracks the last calendar date (JST) we ran a scheduled refresh on.
    last_scheduled_refresh_date_jst: Optional[str] = None


class TokenManager:
    def __init__(self, client: KabuClient):
        self._client = client
        self._lock = threading.RLock()
        self._token: Optional[str] = None
        self.state = TokenState()

    # ---- introspection ----

    def has_token(self) -> bool:
        with self._lock:
            return self._token is not None

    def get_token(self) -> Optional[str]:
        with self._lock:
            return self._token

    def public_state(self) -> dict:
        with self._lock:
            return {
                "token_status": self.state.status,
                "token_last_refreshed_at_utc": self.state.last_refreshed_at_utc,
                "last_refresh_error": self.state.last_refresh_error,
            }

    # ---- mutation ----

    def refresh(self, *, raise_on_fail: bool = False) -> bool:
        """Fetch a fresh token. Returns True on success, False otherwise.

        On failure, sets status=degraded but does not blow away the previous
        token (caller may keep retrying with the old one).
        """
        try:
            new_token = self._client.fetch_token()
        except KabuApiError as e:
            with self._lock:
                self.state.status = "degraded"
                self.state.last_refresh_error = str(e)
            log.warning("token refresh failed: %s", e)
            if raise_on_fail:
                raise
            return False

        now_utc = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._token = new_token
            self.state.status = "valid"
            self.state.last_refreshed_at_utc = now_utc
            self.state.last_refresh_error = None
        log.info("token refreshed at %s", now_utc)
        return True

    def mark_scheduled_refresh_done(self, date_jst: str) -> None:
        with self._lock:
            self.state.last_scheduled_refresh_date_jst = date_jst

    def scheduled_refresh_already_ran(self, date_jst: str) -> bool:
        with self._lock:
            return self.state.last_scheduled_refresh_date_jst == date_jst
