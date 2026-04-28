from tests.conftest import BEARER

H = {"Authorization": f"Bearer {BEARER}"}


def test_status_shape(app_with_seeded_db):
    client, settings = app_with_seeded_db
    r = client.get("/v1/status", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert "collector" in body and "kabu" in body and "storage" in body
    assert body["collector"]["configured_symbol_count"] == len(settings.symbols)
    assert body["storage"]["snapshot_rows"] >= len(settings.symbols)
    # Token should never appear in the response.
    flat = str(body)
    assert "test-api-password" not in flat
    assert "test-bearer-secret" not in flat


def test_symbols_list(app_minimal):
    client, settings = app_minimal
    r = client.get("/v1/symbols", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(settings.symbols)
    assert body["symbols"][0]["api_symbol"] == settings.symbols[0].api_symbol


def test_symbols_filter_by_bucket(app_minimal):
    client, _ = app_minimal
    r = client.get("/v1/symbols?bucket=tier1", headers=H)
    body = r.json()
    assert all(s["bucket"] == "tier1" for s in body["symbols"])
    r = client.get("/v1/symbols?bucket=does-not-exist", headers=H)
    assert r.json() == {"count": 0, "symbols": []}
