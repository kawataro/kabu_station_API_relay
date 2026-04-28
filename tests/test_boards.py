from tests.conftest import BEARER

H = {"Authorization": f"Bearer {BEARER}"}


def test_latest_board_for_known_symbol(app_with_seeded_db):
    client, settings = app_with_seeded_db
    sym = settings.symbols[0].api_symbol
    r = client.get(f"/v1/boards/{sym}", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_symbol"] == sym
    assert body["best_bid_price"] == 500.0
    assert body["best_ask_price"] == 502.0
    assert body["bids"] and body["asks"]
    assert body["source"] == "kabu_board_poll"
    assert "stale" in body
    assert "freshness_ms" in body


def test_latest_board_unknown_symbol_404(app_with_seeded_db):
    client, _ = app_with_seeded_db
    r = client.get("/v1/boards/9999@9", headers=H)
    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "symbol_not_found"


def test_latest_board_known_symbol_no_data_404(app_minimal):
    client, settings = app_minimal
    sym = settings.symbols[0].api_symbol
    r = client.get(f"/v1/boards/{sym}", headers=H)
    assert r.status_code == 404
    assert r.json()["error"] == "symbol_not_found"


def test_bulk_boards_default_returns_all(app_with_seeded_db):
    client, settings = app_with_seeded_db
    r = client.get("/v1/boards", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(settings.symbols)


def test_bulk_boards_filtered(app_with_seeded_db):
    client, settings = app_with_seeded_db
    s = settings.symbols[0].api_symbol
    r = client.get(f"/v1/boards?symbols={s}", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["snapshots"][0]["api_symbol"] == s


def test_bulk_boards_unknown_symbol_400(app_with_seeded_db):
    client, _ = app_with_seeded_db
    r = client.get("/v1/boards?symbols=0000@0", headers=H)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_query"
