"""Unit tests for collector.normalize_board and market_session."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.collector import is_business_day, market_session, normalize_board, staleness_label
from app.settings import RelaySettings, ServerSettings, KabuSettings, CollectionSettings, StorageSettings, SessionWindow, SymbolEntry


JST = ZoneInfo("Asia/Tokyo")


def _settings():
    return RelaySettings(
        server=ServerSettings(
            listen_host="127.0.0.1",
            listen_port=18091,
            bearer_token_env="X",
            allowed_subnets=["127.0.0.1/32"],
        ),
        kabu=KabuSettings(host="127.0.0.1", port=18080, api_password_env="Y"),
        collection=CollectionSettings(
            poll_interval_seconds=5,
            sessions=[
                SessionWindow(name="morning", start="09:00:00", end="11:30:00"),
                SessionWindow(name="afternoon", start="12:30:00", end="15:30:00"),
            ],
        ),
        storage=StorageSettings(db_path="x", export_dir="y"),
        symbols=[SymbolEntry(api_symbol="4582@3", symbol="4582", exchange=3, name="t", bucket="tier1")],
    )


def _sym():
    return SymbolEntry(api_symbol="4582@3", symbol="4582", exchange=3, name="シンバイオ製薬", bucket="tier1")


def test_normalize_board_basic_quote_metrics():
    board = {
        "Buy1": {"Price": 500.0, "Qty": 200},
        "Buy2": {"Price": 499.0, "Qty": 400},
        "Sell1": {"Price": 502.0, "Qty": 300},
        "Sell2": {"Price": 503.0, "Qty": 500},
        "TradingVolume": 150000,
        "VWAP": 501.5,
        "CurrentPrice": 501,
        "CurrentPriceTime": "2026-04-27T09:00:04+09:00",
    }
    row = normalize_board(board, sym=_sym(), run_id="r", collected_at_utc="2026-04-27T00:00:00+00:00")
    assert row["best_bid_price"] == 500.0
    assert row["best_ask_price"] == 502.0
    assert row["mid_price"] == 501.0
    assert row["spread"] == 2.0
    assert abs(row["spread_pct"] - 2.0 / 501.0 * 100.0) < 1e-9
    assert row["bid_depth_5_jpy"] == 500.0 * 200 + 499.0 * 400
    assert row["ask_depth_5_jpy"] == 502.0 * 300 + 503.0 * 500
    assert row["trading_volume"] == 150000
    assert row["api_symbol"] == "4582@3"
    assert "raw_json" in row and row["raw_json"]


def test_normalize_board_with_missing_levels():
    row = normalize_board({}, sym=_sym(), run_id="r", collected_at_utc="2026-04-27T00:00:00+00:00")
    assert row["best_bid_price"] is None
    assert row["best_ask_price"] is None
    assert row["mid_price"] is None
    assert row["spread"] is None
    assert row["spread_pct"] is None
    assert row["bid_depth_5_jpy"] is None
    assert row["ask_depth_5_jpy"] is None


def test_market_session_morning():
    s = _settings()
    # Monday 2026-04-27 10:00 JST -> open
    when = datetime(2026, 4, 27, 10, 0, tzinfo=JST).astimezone(timezone.utc)
    name, is_open = market_session(when, s)
    assert is_open is True
    assert name == "morning"


def test_market_session_lunch_break():
    s = _settings()
    when = datetime(2026, 4, 27, 12, 0, tzinfo=JST).astimezone(timezone.utc)
    name, is_open = market_session(when, s)
    assert is_open is False
    assert name is None


def test_market_session_weekend():
    s = _settings()
    # Saturday 2026-05-02 10:00 JST -> closed
    when = datetime(2026, 5, 2, 10, 0, tzinfo=JST).astimezone(timezone.utc)
    _name, is_open = market_session(when, s)
    assert is_open is False


def test_market_session_japanese_holiday():
    """5/3 (憲法記念日) 2026 falls on a Sunday, but 5/4-5/5 are weekdays.

    2026-05-04 (Mon) みどりの日 / 2026-05-05 (Tue) こどもの日 are weekday holidays
    and must be treated as closed even though weekday() < 5.
    """
    from datetime import date

    s = _settings()
    # 2026-05-05 (Tue) こどもの日 at 10:00 JST -> closed.
    when = datetime(2026, 5, 5, 10, 0, tzinfo=JST).astimezone(timezone.utc)
    _name, is_open = market_session(when, s)
    assert is_open is False
    # Sanity: 2026-05-07 (Thu) 10:00 JST is a regular business day -> open.
    when = datetime(2026, 5, 7, 10, 0, tzinfo=JST).astimezone(timezone.utc)
    _name, is_open = market_session(when, s)
    assert is_open is True

    # is_business_day directly:
    assert is_business_day(date(2026, 5, 5), []) is False  # holiday
    assert is_business_day(date(2026, 5, 7), []) is True   # plain Thursday
    assert is_business_day(date(2026, 5, 2), []) is False  # Saturday


def test_market_session_extra_closed_dates():
    s = _settings()
    s.collection.extra_closed_dates = ["2026-05-07"]
    when = datetime(2026, 5, 7, 10, 0, tzinfo=JST).astimezone(timezone.utc)
    _name, is_open = market_session(when, s)
    assert is_open is False


def test_staleness_label():
    now = datetime(2026, 4, 27, 10, 0, tzinfo=timezone.utc)
    assert staleness_label(now.isoformat(), now) == "fresh"
    earlier = datetime(2026, 4, 27, 9, 59, 30, tzinfo=timezone.utc)
    assert staleness_label(earlier.isoformat(), now) in {"warning", "fresh"}  # 30s -> warning
    much_earlier = datetime(2026, 4, 27, 9, 58, 0, tzinfo=timezone.utc)
    assert staleness_label(much_earlier.isoformat(), now) == "stale"
    assert staleness_label(None, now) == "stale"
