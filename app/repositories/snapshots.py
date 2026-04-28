"""orderbook_snapshots queries."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from ..db import connect


_BASE_COLS = (
    "id, run_id, collected_at, symbol, symbol_name, bucket, exchange, api_symbol,"
    " best_bid_price, best_bid_qty, best_ask_price, best_ask_qty,"
    " mid_price, spread, spread_pct,"
    " bid_depth_5_jpy, ask_depth_5_jpy, bids_json, asks_json,"
    " trading_volume, vwap, current_price, current_price_time"
)


def _row_to_snapshot(row: sqlite3.Row) -> dict[str, Any]:
    bids = json.loads(row["bids_json"]) if row["bids_json"] else []
    asks = json.loads(row["asks_json"]) if row["asks_json"] else []
    return {
        "id": row["id"],
        "api_symbol": row["api_symbol"],
        "symbol": row["symbol"],
        "exchange": row["exchange"],
        "symbol_name": row["symbol_name"],
        "bucket": row["bucket"],
        "collected_at_utc": row["collected_at"],
        "source_current_price_time": row["current_price_time"],
        "current_price": row["current_price"],
        "trading_volume": row["trading_volume"],
        "vwap": row["vwap"],
        "best_bid_price": row["best_bid_price"],
        "best_bid_qty": row["best_bid_qty"],
        "best_ask_price": row["best_ask_price"],
        "best_ask_qty": row["best_ask_qty"],
        "mid_price": row["mid_price"],
        "spread": row["spread"],
        "spread_pct": row["spread_pct"],
        "bid_depth_5_jpy": row["bid_depth_5_jpy"],
        "ask_depth_5_jpy": row["ask_depth_5_jpy"],
        "bids": bids,
        "asks": asks,
        "source": "kabu_board_poll",
    }


def _row_to_history_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "collected_at_utc": row["collected_at"],
        "best_bid_price": row["best_bid_price"],
        "best_bid_qty": row["best_bid_qty"],
        "best_ask_price": row["best_ask_price"],
        "best_ask_qty": row["best_ask_qty"],
        "spread_pct": row["spread_pct"],
        "trading_volume": row["trading_volume"],
        "current_price": row["current_price"],
    }


def latest_for_symbol(db_path: str, api_symbol: str) -> Optional[dict[str, Any]]:
    with connect(db_path, read_only=True) as conn:
        cur = conn.execute(
            f"SELECT {_BASE_COLS} FROM orderbook_snapshots"
            " WHERE api_symbol = ?"
            " ORDER BY collected_at DESC LIMIT 1",
            (api_symbol,),
        )
        row = cur.fetchone()
    return _row_to_snapshot(row) if row else None


def latest_for_symbols(db_path: str, api_symbols: list[str]) -> list[dict[str, Any]]:
    if not api_symbols:
        return []
    out: list[dict[str, Any]] = []
    with connect(db_path, read_only=True) as conn:
        for s in api_symbols:
            cur = conn.execute(
                f"SELECT {_BASE_COLS} FROM orderbook_snapshots"
                " WHERE api_symbol = ?"
                " ORDER BY collected_at DESC LIMIT 1",
                (s,),
            )
            row = cur.fetchone()
            if row:
                out.append(_row_to_snapshot(row))
    return out


def history(
    db_path: str,
    *,
    api_symbol: str,
    from_iso: Optional[str] = None,
    to_iso: Optional[str] = None,
    limit: int = 500,
    order: str = "desc",
    cursor_id: Optional[int] = None,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    limit = max(1, min(limit, 5000))
    where = ["api_symbol = ?"]
    args: list[Any] = [api_symbol]
    if from_iso:
        where.append("collected_at >= ?")
        args.append(from_iso)
    if to_iso:
        where.append("collected_at <= ?")
        args.append(to_iso)
    if cursor_id is not None:
        where.append("id < ?" if order == "desc" else "id > ?")
        args.append(cursor_id)
    order_sql = "DESC" if order == "desc" else "ASC"
    sql = (
        f"SELECT {_BASE_COLS} FROM orderbook_snapshots"
        f" WHERE {' AND '.join(where)}"
        f" ORDER BY id {order_sql}"
        f" LIMIT ?"
    )
    args.append(limit + 1)  # +1 to detect more
    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(sql, args).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    out = [_row_to_history_row(r) for r in rows]
    next_cursor: Optional[str] = None
    if has_more and out:
        next_cursor = str(rows[-1]["id"])
    return out, next_cursor


def total_row_count(db_path: str) -> int:
    with connect(db_path, read_only=True) as conn:
        cur = conn.execute("SELECT COUNT(1) AS c FROM orderbook_snapshots")
        row = cur.fetchone()
    return int(row["c"]) if row else 0


def latest_collected_at(db_path: str) -> Optional[str]:
    with connect(db_path, read_only=True) as conn:
        cur = conn.execute(
            "SELECT MAX(collected_at) AS t FROM orderbook_snapshots"
        )
        row = cur.fetchone()
    return row["t"] if row and row["t"] else None
