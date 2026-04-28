from tests.conftest import BEARER, _seed_snapshot

H = {"Authorization": f"Bearer {BEARER}"}


def test_snapshots_history_returns_rows(app_with_seeded_db):
    client, settings = app_with_seeded_db
    sym = settings.symbols[0].api_symbol
    # add a couple more rows for that symbol
    for _ in range(3):
        _seed_snapshot(settings.storage.db_path, api_symbol=sym, run_id="extra")
    r = client.get(f"/v1/snapshots?symbol={sym}&limit=10", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"] == sym
    assert body["count"] >= 4
    assert all("collected_at_utc" in row for row in body["rows"])


def test_snapshots_history_unknown_symbol_404(app_with_seeded_db):
    client, _ = app_with_seeded_db
    r = client.get("/v1/snapshots?symbol=9999@9", headers=H)
    assert r.status_code == 404


def test_snapshots_invalid_cursor_400(app_with_seeded_db):
    client, settings = app_with_seeded_db
    sym = settings.symbols[0].api_symbol
    r = client.get(f"/v1/snapshots?symbol={sym}&cursor=not-an-int", headers=H)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_query"


def test_snapshots_limit_capped_to_5000(app_with_seeded_db):
    client, settings = app_with_seeded_db
    sym = settings.symbols[0].api_symbol
    r = client.get(f"/v1/snapshots?symbol={sym}&limit=99999", headers=H)
    # FastAPI Query(le=5000) catches this in our validation handler.
    assert r.status_code == 400
