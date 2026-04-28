"""Auth: 401 without bearer, 403 outside allowlist, 200 with both."""

from tests.conftest import BEARER


def test_status_requires_bearer(app_minimal):
    client, _ = app_minimal
    r = client.get("/v1/status")
    assert r.status_code == 401
    body = r.json()
    assert body["error"] == "unauthorized"


def test_status_rejects_wrong_bearer(app_minimal):
    client, _ = app_minimal
    r = client.get("/v1/status", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_status_ok_with_bearer(app_minimal):
    client, _ = app_minimal
    r = client.get("/v1/status", headers={"Authorization": f"Bearer {BEARER}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["collector"]["configured_symbol_count"] == 3


def test_ip_outside_allowlist_blocked(app_minimal):
    """TestClient gives client.host='testclient' which is outside 127.0.0.1/32.

    We tighten the subnet to a non-matching range and expect 403.
    """
    client, settings = app_minimal
    # Replace allowed_subnets with a range that excludes testclient/127.0.0.1.
    settings.server.allowed_subnets = ["10.255.255.0/30"]
    r = client.get("/v1/status", headers={"Authorization": f"Bearer {BEARER}"})
    assert r.status_code == 403
    body = r.json()
    assert body["error"] == "forbidden_ip"
