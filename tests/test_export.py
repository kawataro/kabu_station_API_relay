from pathlib import Path

from tests.conftest import BEARER

H = {"Authorization": f"Bearer {BEARER}"}


def test_export_meta_empty_initially(app_minimal):
    client, _ = app_minimal
    r = client.get("/v1/export/meta", headers=H)
    assert r.status_code == 200
    assert r.json() == {"latest_export": None}


def test_export_sqlite_latest_returns_frozen_db(app_with_seeded_db):
    client, settings = app_with_seeded_db
    r = client.get("/v1/export/sqlite/latest", headers=H)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/octet-stream")
    body = r.content
    # SQLite files start with the magic header.
    assert body.startswith(b"SQLite format 3\x00")
    # File should not be the live DB path itself.
    live = Path(settings.storage.db_path).resolve()
    export_dir = Path(settings.storage.export_dir).resolve()
    files = list(export_dir.glob("kabu_orderbook_snapshot_*.db"))
    assert files, "frozen export file was not created"
    for f in files:
        assert f.resolve() != live


def test_export_meta_after_export(app_with_seeded_db):
    client, _ = app_with_seeded_db
    client.get("/v1/export/sqlite/latest", headers=H)
    r = client.get("/v1/export/meta", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["latest_export"] is not None
    meta = body["latest_export"]
    assert meta["snapshot_rows"] >= 1
    assert meta["file_size_bytes"] > 0
    assert meta["file_name"].startswith("kabu_orderbook_snapshot_")
