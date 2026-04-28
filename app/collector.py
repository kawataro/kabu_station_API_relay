"""Polling collector.

Responsibilities:
- gate by JST market sessions (前場 09:00-11:30 / 後場 12:30-15:30, weekdays).
- iterate configured symbols once per poll cycle.
- normalize each board response into the snapshot row shape.
- insert snapshots, detect best-quote changes, write price_changes.
- expose a thread-safe `Status` for /v1/status to read.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

try:
    import jpholiday  # type: ignore
    _HAVE_JPHOLIDAY = True
except ImportError:  # pragma: no cover
    _HAVE_JPHOLIDAY = False

from .db import connect
from .kabu_client import KabuApiError, KabuClient, KabuUnauthorizedError
from .settings import RelaySettings, SymbolEntry
from .token_manager import TokenManager


log = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")
UTC = timezone.utc


# ---------------- normalization helpers ----------------


def _f(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _extract_levels(board: dict[str, Any], side: str) -> list[dict[str, Any]]:
    """kabu board has Buy1..Buy10 and Sell1..Sell10."""
    prefix = "Buy" if side == "bid" else "Sell"
    levels: list[dict[str, Any]] = []
    for i in range(1, 11):
        node = board.get(f"{prefix}{i}")
        if not isinstance(node, dict):
            continue
        price = _f(node.get("Price"))
        qty = _f(node.get("Qty"))
        if price is None and qty is None:
            continue
        levels.append({"level": i, "price": price, "qty": qty})
    return levels


def _depth_jpy(levels: list[dict[str, Any]], n: int = 5) -> Optional[float]:
    total = 0.0
    counted = 0
    for lv in levels[:n]:
        p = lv.get("price")
        q = lv.get("qty")
        if p is None or q is None:
            continue
        total += p * q
        counted += 1
    return total if counted > 0 else None


def normalize_board(
    board: dict[str, Any],
    *,
    sym: SymbolEntry,
    run_id: str,
    collected_at_utc: str,
) -> dict[str, Any]:
    bids = _extract_levels(board, "bid")
    asks = _extract_levels(board, "ask")

    best_bid_price = bids[0]["price"] if bids else None
    best_bid_qty = bids[0]["qty"] if bids else None
    best_ask_price = asks[0]["price"] if asks else None
    best_ask_qty = asks[0]["qty"] if asks else None

    spread = None
    if best_bid_price is not None and best_ask_price is not None:
        spread = best_ask_price - best_bid_price
    mid_price = None
    if best_bid_price is not None and best_ask_price is not None:
        mid_price = (best_bid_price + best_ask_price) / 2.0
    spread_pct = None
    if spread is not None and mid_price not in (None, 0):
        spread_pct = (spread / mid_price) * 100.0

    return {
        "run_id": run_id,
        "collected_at": collected_at_utc,
        "symbol": sym.symbol,
        "symbol_name": sym.name,
        "bucket": sym.bucket,
        "exchange": sym.exchange,
        "api_symbol": sym.api_symbol,
        "best_bid_price": best_bid_price,
        "best_bid_qty": best_bid_qty,
        "best_ask_price": best_ask_price,
        "best_ask_qty": best_ask_qty,
        "mid_price": mid_price,
        "spread": spread,
        "spread_pct": spread_pct,
        "bid_depth_5_jpy": _depth_jpy(bids, 5),
        "ask_depth_5_jpy": _depth_jpy(asks, 5),
        "bids_json": json.dumps(bids, ensure_ascii=False),
        "asks_json": json.dumps(asks, ensure_ascii=False),
        "trading_volume": _f(board.get("TradingVolume")),
        "vwap": _f(board.get("VWAP")),
        "current_price": _f(board.get("CurrentPrice")),
        "current_price_time": board.get("CurrentPriceTime"),
        "raw_json": json.dumps(board, ensure_ascii=False),
    }


# ---------------- session gate ----------------


def _parse_hms(s: str) -> dtime:
    h, m, sec = (int(x) for x in s.split(":"))
    return dtime(h, m, sec)


def is_jp_holiday(d: date) -> bool:
    """True if `d` is a Japanese national holiday."""
    if _HAVE_JPHOLIDAY:
        return bool(jpholiday.is_holiday(d))
    return False


def is_business_day(d: date, extra_closed: list[str]) -> bool:
    """JST business day: Mon–Fri, excluding national holidays and extras."""
    if d.weekday() >= 5:
        return False
    if is_jp_holiday(d):
        return False
    if d.isoformat() in (extra_closed or []):
        return False
    return True


def market_session(now_utc: datetime, settings: RelaySettings) -> tuple[Optional[str], bool]:
    """Return (session_name|None, is_market_open) in JST terms.

    Closed conditions, in order:
      - business_days_only=True and the JST date is a weekend / holiday / extra.
      - the JST clock is outside any configured session window.
    """
    now_jst = now_utc.astimezone(JST)
    if settings.collection.business_days_only and not is_business_day(
        now_jst.date(), settings.collection.extra_closed_dates
    ):
        return None, False
    t = now_jst.time().replace(microsecond=0)
    for win in settings.collection.sessions:
        start = _parse_hms(win.start)
        end = _parse_hms(win.end)
        if start <= t < end:
            return win.name, True
    return None, False


# ---------------- status ----------------


@dataclass
class CollectorStatus:
    running: bool = False
    mode: str = "poll"
    poll_interval_seconds: float = 5.0
    configured_symbol_count: int = 0
    last_success_at_utc: Optional[str] = None
    last_error_at_utc: Optional[str] = None
    last_error_message: Optional[str] = None
    consecutive_error_count: int = 0
    last_cycle_duration_seconds: Optional[float] = None
    market_session: Optional[str] = None
    market_open: bool = False
    kabu_reachable: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.running,
                "mode": self.mode,
                "poll_interval_seconds": self.poll_interval_seconds,
                "configured_symbol_count": self.configured_symbol_count,
                "last_success_at_utc": self.last_success_at_utc,
                "last_error_at_utc": self.last_error_at_utc,
                "last_error_message": self.last_error_message,
                "consecutive_error_count": self.consecutive_error_count,
                "last_cycle_duration_seconds": self.last_cycle_duration_seconds,
                "market_session": self.market_session,
                "market_open": self.market_open,
                "kabu_reachable": self.kabu_reachable,
            }


# ---------------- collector core ----------------


SNAPSHOT_INSERT = """
INSERT INTO orderbook_snapshots (
    run_id, collected_at, symbol, symbol_name, bucket, exchange, api_symbol,
    best_bid_price, best_bid_qty, best_ask_price, best_ask_qty,
    mid_price, spread, spread_pct,
    bid_depth_5_jpy, ask_depth_5_jpy,
    bids_json, asks_json,
    trading_volume, vwap, current_price, current_price_time,
    raw_json
) VALUES (
    :run_id, :collected_at, :symbol, :symbol_name, :bucket, :exchange, :api_symbol,
    :best_bid_price, :best_bid_qty, :best_ask_price, :best_ask_qty,
    :mid_price, :spread, :spread_pct,
    :bid_depth_5_jpy, :ask_depth_5_jpy,
    :bids_json, :asks_json,
    :trading_volume, :vwap, :current_price, :current_price_time,
    :raw_json
)
"""

PRICE_CHANGE_INSERT = """
INSERT INTO price_changes (
    run_id, detected_at, symbol, api_symbol, change_type,
    prev_best_bid, prev_best_ask, new_best_bid, new_best_ask,
    prev_spread_pct, new_spread_pct,
    best_bid_duration_sec, best_ask_duration_sec
) VALUES (
    :run_id, :detected_at, :symbol, :api_symbol, :change_type,
    :prev_best_bid, :prev_best_ask, :new_best_bid, :new_best_ask,
    :prev_spread_pct, :new_spread_pct,
    :best_bid_duration_sec, :best_ask_duration_sec
)
"""


class Collector:
    def __init__(
        self,
        settings: RelaySettings,
        client: KabuClient,
        token_mgr: TokenManager,
    ):
        self.settings = settings
        self.client = client
        self.token_mgr = token_mgr
        self.status = CollectorStatus(
            mode=settings.collection.mode,
            poll_interval_seconds=settings.collection.poll_interval_seconds,
            configured_symbol_count=len(settings.symbols),
        )
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.run_id = uuid.uuid4().hex

        # In-memory tracking for price-change detection.
        # key = api_symbol, value = (best_bid, best_ask, spread_pct, bid_seen_at, ask_seen_at)
        self._last_quote: dict[str, dict[str, Any]] = {}

    # --- lifecycle ---

    def start(self) -> None:
        with connect(self.settings.storage.db_path) as conn:
            conn.execute(
                "INSERT INTO collector_runs (run_id, started_at, config_path, db_path, status, notes)"
                " VALUES (?, ?, ?, ?, 'running', NULL)",
                (
                    self.run_id,
                    datetime.now(UTC).isoformat(),
                    self.settings.config_path,
                    self.settings.storage.db_path,
                ),
            )
        self._thread = threading.Thread(
            target=self._loop,
            name="kabu-relay-collector",
            daemon=True,
        )
        self.status.running = True
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self.status.running = False
        try:
            with connect(self.settings.storage.db_path) as conn:
                conn.execute(
                    "UPDATE collector_runs SET status='completed' WHERE run_id=?",
                    (self.run_id,),
                )
        except sqlite3.Error:
            log.warning("could not finalize collector_runs row", exc_info=True)

    # --- main loop ---

    def _loop(self) -> None:
        log.info(
            "collector started run_id=%s symbols=%d interval=%ss",
            self.run_id,
            len(self.settings.symbols),
            self.settings.collection.poll_interval_seconds,
        )
        interval = self.settings.collection.poll_interval_seconds
        while not self._stop.is_set():
            cycle_started = time.monotonic()
            now = datetime.now(UTC)
            session, is_open = market_session(now, self.settings)
            with self.status._lock:
                self.status.market_session = session
                self.status.market_open = is_open

            self._maybe_scheduled_token_refresh(now)

            if is_open:
                try:
                    self._cycle(now)
                except Exception as e:  # noqa: BLE001
                    log.exception("collector cycle failed: %s", e)
                    self._record_error(str(e))
            # Sleep the remainder of the interval, but exit promptly on stop.
            elapsed = time.monotonic() - cycle_started
            with self.status._lock:
                self.status.last_cycle_duration_seconds = elapsed
            remaining = max(0.5, interval - elapsed)
            self._stop.wait(timeout=remaining)

    def _maybe_scheduled_token_refresh(self, now_utc: datetime) -> None:
        cfg = self.settings.kabu.token_refresh
        if not cfg or not cfg.daily_refresh_jst:
            return
        now_jst = now_utc.astimezone(JST)
        target = _parse_hms(cfg.daily_refresh_jst)
        # Run once per JST date when within ±5 minutes of the target time.
        target_dt = datetime.combine(now_jst.date(), target, tzinfo=JST)
        delta = (now_jst - target_dt).total_seconds()
        if -300 <= delta <= 600 and not self.token_mgr.scheduled_refresh_already_ran(
            now_jst.date().isoformat()
        ):
            log.info("running scheduled token refresh for %s JST", now_jst.date())
            self.token_mgr.refresh()
            self.token_mgr.mark_scheduled_refresh_done(now_jst.date().isoformat())

    def _cycle(self, now_utc: datetime) -> None:
        cycle_id = uuid.uuid4().hex[:8]
        started = time.monotonic()
        log.info(
            "collector cycle start id=%s symbols=%d run=%s",
            cycle_id,
            len(self.settings.symbols),
            self.run_id,
        )
        fetched = 0
        errors = 0
        for sym in self.settings.symbols:
            if self._stop.is_set():
                break
            try:
                board = self._fetch_with_retry(sym.api_symbol)
            except KabuApiError as e:
                errors += 1
                self._record_error(f"{sym.api_symbol}: {e}")
                self._record_api_error(sym, e)
                continue
            collected_at = datetime.now(UTC).isoformat()
            row = normalize_board(
                board, sym=sym, run_id=self.run_id, collected_at_utc=collected_at
            )
            self._insert_snapshot_and_detect_changes(row, sym, collected_at)
            fetched += 1

        if fetched > 0:
            with self.status._lock:
                self.status.last_success_at_utc = datetime.now(UTC).isoformat()
                self.status.consecutive_error_count = 0
                self.status.kabu_reachable = True

        duration = time.monotonic() - started
        log.info(
            "collector cycle end   id=%s fetched=%d errors=%d duration=%.3fs",
            cycle_id,
            fetched,
            errors,
            duration,
        )

    def _fetch_with_retry(self, api_symbol: str) -> dict[str, Any]:
        token = self.token_mgr.get_token()
        if token is None:
            # Try to acquire one if we lost it; still raise if it doesn't come.
            if not self.token_mgr.refresh():
                raise KabuApiError("no token available")
            token = self.token_mgr.get_token()
            assert token is not None
        try:
            return self.client.fetch_board(api_symbol, token)
        except KabuUnauthorizedError:
            log.info("got 401 for %s; refreshing token once and retrying", api_symbol)
            if not self.token_mgr.refresh():
                raise
            token = self.token_mgr.get_token()
            assert token is not None
            return self.client.fetch_board(api_symbol, token)

    # --- writes ---

    def _insert_snapshot_and_detect_changes(
        self, row: dict[str, Any], sym: SymbolEntry, collected_at_utc: str
    ) -> None:
        with connect(self.settings.storage.db_path) as conn:
            conn.execute(SNAPSHOT_INSERT, row)
            change = self._detect_change(row, sym, collected_at_utc)
            if change is not None:
                conn.execute(PRICE_CHANGE_INSERT, change)

    def _detect_change(
        self, row: dict[str, Any], sym: SymbolEntry, collected_at_utc: str
    ) -> Optional[dict[str, Any]]:
        prev = self._last_quote.get(sym.api_symbol)
        new_bid = row["best_bid_price"]
        new_ask = row["best_ask_price"]
        new_spread_pct = row["spread_pct"]
        now_dt = datetime.fromisoformat(collected_at_utc)

        change: Optional[dict[str, Any]] = None
        if prev is not None:
            bid_changed = prev["best_bid_price"] != new_bid
            ask_changed = prev["best_ask_price"] != new_ask
            if bid_changed or ask_changed:
                bid_dur = (
                    (now_dt - prev["bid_seen_at"]).total_seconds()
                    if prev["bid_seen_at"] is not None
                    else None
                )
                ask_dur = (
                    (now_dt - prev["ask_seen_at"]).total_seconds()
                    if prev["ask_seen_at"] is not None
                    else None
                )
                change = {
                    "run_id": self.run_id,
                    "detected_at": collected_at_utc,
                    "symbol": sym.symbol,
                    "api_symbol": sym.api_symbol,
                    "change_type": "best_quote_changed",
                    "prev_best_bid": prev["best_bid_price"],
                    "prev_best_ask": prev["best_ask_price"],
                    "new_best_bid": new_bid,
                    "new_best_ask": new_ask,
                    "prev_spread_pct": prev["spread_pct"],
                    "new_spread_pct": new_spread_pct,
                    "best_bid_duration_sec": bid_dur if bid_changed else None,
                    "best_ask_duration_sec": ask_dur if ask_changed else None,
                }

        # update tracker
        prev_bid_seen = prev["bid_seen_at"] if prev else None
        prev_ask_seen = prev["ask_seen_at"] if prev else None
        bid_changed_for_tracker = prev is None or prev["best_bid_price"] != new_bid
        ask_changed_for_tracker = prev is None or prev["best_ask_price"] != new_ask
        self._last_quote[sym.api_symbol] = {
            "best_bid_price": new_bid,
            "best_ask_price": new_ask,
            "spread_pct": new_spread_pct,
            "bid_seen_at": now_dt if bid_changed_for_tracker else prev_bid_seen,
            "ask_seen_at": now_dt if ask_changed_for_tracker else prev_ask_seen,
        }
        return change

    def _record_error(self, message: str) -> None:
        now_utc = datetime.now(UTC).isoformat()
        with self.status._lock:
            self.status.last_error_at_utc = now_utc
            self.status.last_error_message = message
            self.status.consecutive_error_count += 1
            if self.status.consecutive_error_count >= 3:
                self.status.kabu_reachable = False

    def _record_api_error(self, sym: SymbolEntry, e: KabuApiError) -> None:
        try:
            with connect(self.settings.storage.db_path) as conn:
                conn.execute(
                    "INSERT INTO api_errors (occurred_at, component, symbol, error_type, message, retryable)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        datetime.now(UTC).isoformat(),
                        "collector",
                        sym.api_symbol,
                        type(e).__name__,
                        str(e)[:500],
                        1,
                    ),
                )
        except sqlite3.Error:
            log.warning("could not write api_errors", exc_info=True)


# ---------------- staleness ----------------


def staleness_label(latest_utc: Optional[str], now_utc: datetime) -> str:
    if not latest_utc:
        return "stale"
    try:
        t = datetime.fromisoformat(latest_utc)
    except ValueError:
        return "stale"
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    age = (now_utc - t).total_seconds()
    if age <= 15:
        return "fresh"
    if age <= 60:
        return "warning"
    return "stale"
