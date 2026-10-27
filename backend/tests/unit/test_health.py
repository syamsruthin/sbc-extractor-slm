def test_health_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] is True
    assert body["version"]
    assert r.headers["x-request-id"]


def test_request_id_is_echoed(client):
    r = client.get("/api/v1/health", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
