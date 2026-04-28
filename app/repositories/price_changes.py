"""price_changes queries."""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from ..db import connect


def _row_to_price_change(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "detected_at_utc": row["detected_at"],
        "symbol": row["symbol"],
        "api_symbol": row["api_symbol"],
        "change_type": row["change_type"],
        "prev_best_bid": row["prev_best_bid"],
        "prev_best_ask": row["prev_best_ask"],
        "new_best_bid": row["new_best_bid"],
        "new_best_ask": row["new_best_ask"],
        "prev_spread_pct": row["prev_spread_pct"],
        "new_spread_pct": row["new_spread_pct"],
        "best_bid_duration_sec": row["best_bid_duration_sec"],
        "best_ask_duration_sec": row["best_ask_duration_sec"],
    }


def history(
    db_path: str,
    *,
    symbol: str,
    from_iso: Optional[str] = None,
    to_iso: Optional[str] = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 5000))
    where = ["(symbol = ? OR api_symbol = ?)"]
    args: list[Any] = [symbol, symbol]
    if from_iso:
        where.append("detected_at >= ?")
        args.append(from_iso)
    if to_iso:
        where.append("detected_at <= ?")
        args.append(to_iso)
    sql = (
        "SELECT id, detected_at, symbol, api_symbol, change_type,"
        " prev_best_bid, prev_best_ask, new_best_bid, new_best_ask,"
        " prev_spread_pct, new_spread_pct,"
        " best_bid_duration_sec, best_ask_duration_sec"
        " FROM price_changes"
        f" WHERE {' AND '.join(where)}"
        " ORDER BY id DESC LIMIT ?"
    )
    args.append(limit)
    with connect(db_path, read_only=True) as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_price_change(r) for r in rows]


def total_row_count(db_path: str) -> int:
    with connect(db_path, read_only=True) as conn:
        cur = conn.execute("SELECT COUNT(1) AS c FROM price_changes")
        row = cur.fetchone()
    return int(row["c"]) if row else 0
