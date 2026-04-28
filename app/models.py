"""Pydantic response models. Kept loose where the underlying data is None-able."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class HealthResponse(BaseModel):
    ok: bool
    service: str
    version: str


class ErrorResponse(BaseModel):
    error: str
    message: str


class SymbolOut(BaseModel):
    api_symbol: str
    symbol: str
    exchange: int
    name: str
    bucket: str


class SymbolListResponse(BaseModel):
    count: int
    symbols: list[SymbolOut]


class BoardLevel(BaseModel):
    level: int
    price: Optional[float] = None
    qty: Optional[float] = None


class LatestSnapshot(BaseModel):
    api_symbol: str
    symbol: str
    exchange: Optional[int] = None
    symbol_name: Optional[str] = None
    bucket: Optional[str] = None
    collected_at_utc: str
    source_current_price_time: Optional[str] = None
    current_price: Optional[float] = None
    trading_volume: Optional[float] = None
    vwap: Optional[float] = None
    best_bid_price: Optional[float] = None
    best_bid_qty: Optional[float] = None
    best_ask_price: Optional[float] = None
    best_ask_qty: Optional[float] = None
    mid_price: Optional[float] = None
    spread: Optional[float] = None
    spread_pct: Optional[float] = None
    bid_depth_5_jpy: Optional[float] = None
    ask_depth_5_jpy: Optional[float] = None
    bids: list[BoardLevel] = []
    asks: list[BoardLevel] = []
    source: str = "kabu_board_poll"
    freshness_ms: Optional[int] = None
    stale: bool = False


class BoardsBulkResponse(BaseModel):
    count: int
    snapshots: list[LatestSnapshot]


class SnapshotHistoryRow(BaseModel):
    id: int
    collected_at_utc: str
    best_bid_price: Optional[float] = None
    best_bid_qty: Optional[float] = None
    best_ask_price: Optional[float] = None
    best_ask_qty: Optional[float] = None
    spread_pct: Optional[float] = None
    trading_volume: Optional[float] = None
    current_price: Optional[float] = None


class SnapshotHistoryResponse(BaseModel):
    symbol: str
    count: int
    next_cursor: Optional[str] = None
    rows: list[SnapshotHistoryRow]


class PriceChangeRow(BaseModel):
    id: int
    detected_at_utc: str
    symbol: str
    api_symbol: Optional[str] = None
    change_type: str
    prev_best_bid: Optional[float] = None
    prev_best_ask: Optional[float] = None
    new_best_bid: Optional[float] = None
    new_best_ask: Optional[float] = None
    prev_spread_pct: Optional[float] = None
    new_spread_pct: Optional[float] = None
    best_bid_duration_sec: Optional[float] = None
    best_ask_duration_sec: Optional[float] = None


class PriceChangeResponse(BaseModel):
    count: int
    rows: list[PriceChangeRow]


class ExportMeta(BaseModel):
    created_at_utc: str
    file_name: str
    file_size_bytes: int
    snapshot_rows: int
    price_change_rows: int
    latest_snapshot_at_utc: Optional[str] = None


class ExportMetaResponse(BaseModel):
    latest_export: Optional[ExportMeta] = None


# Status response uses dict[str, Any] in routes; we don't model strictly here.
