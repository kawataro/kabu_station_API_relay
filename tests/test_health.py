def test_health_no_auth(app_minimal):
    client, _settings = app_minimal
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["service"] == "kabu-relay"
    assert body["version"] == "v1"
