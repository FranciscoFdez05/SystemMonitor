"""API HTTP: autenticacion, endpoints protegidos, health y WebSocket."""
from __future__ import annotations

import pytest

PROTECTED = [
    "/api/me",
    "/api/metrics/now",
    "/api/metrics/history?minutes=60",
    "/api/processes",
    "/api/network/connections",
    "/api/alerts/rules",
]


@pytest.mark.parametrize("path", PROTECTED)
def test_protected_endpoints_require_login(client, path):
    client.cookies.clear()
    assert client.get(path).status_code == 401


def test_health_is_public_and_reports_the_scheduler(client):
    client.cookies.clear()
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["scheduler"]["running"] is True


def test_root_redirects_to_login_when_anonymous(client):
    client.cookies.clear()
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_login_rejects_bad_password(client):
    client.cookies.clear()
    response = client.post("/api/login", json={"username": "tester", "password": "mal"})
    assert response.status_code == 401


def test_login_sets_httponly_cookie(client):
    client.cookies.clear()
    response = client.post("/api/login",
                           json={"username": "tester", "password": "secreto-de-prueba"})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    # httponly es lo que impide leer la sesion desde JS inyectado.
    assert "httponly" in cookie.lower()


def test_metrics_snapshot_has_the_live_channels(auth_client):
    body = auth_client.get("/api/metrics/now").json()
    for channel in ("cpu", "memory", "thermal", "network", "system"):
        assert channel in body, f"falta el canal {channel}"


def test_history_returns_a_bucketed_series(auth_client):
    body = auth_client.get("/api/metrics/history?minutes=60&max_points=60").json()
    assert body["bucket_seconds"] >= 60
    assert isinstance(body["series"], list)


def test_default_alert_rules_are_seeded(auth_client):
    body = auth_client.get("/api/alerts/rules").json()
    names = {rule["name"] for rule in body["rules"]}
    assert "Disco raiz al 90%" in names
    assert body["sinks"]["log"] is True


def test_alert_rule_crud(auth_client):
    created = auth_client.post("/api/alerts/rules", json={
        "name": "Regla de prueba", "metric": "memory", "operator": "gt",
        "threshold": 95, "duration_s": 30, "cooldown_s": 60, "sinks": ["log"],
    })
    assert created.status_code == 201
    rule_id = created.json()["id"]

    updated = auth_client.put(f"/api/alerts/rules/{rule_id}", json={
        "name": "Regla editada", "metric": "memory", "operator": "gt",
        "threshold": 97, "duration_s": 30, "cooldown_s": 60, "sinks": ["log"],
    })
    assert updated.status_code == 200

    assert auth_client.delete(f"/api/alerts/rules/{rule_id}").status_code == 200
    assert auth_client.delete(f"/api/alerts/rules/{rule_id}").status_code == 404


def test_alert_rule_rejects_unknown_sink(auth_client):
    response = auth_client.post("/api/alerts/rules", json={
        "name": "mala", "metric": "cpu", "threshold": 50, "sinks": ["carrier-pigeon"],
    })
    assert response.status_code == 422


def test_cannot_kill_pid_one(auth_client):
    response = auth_client.delete("/api/processes/1")
    # El path exige pid >= 2, asi que ni siquiera llega al handler.
    assert response.status_code == 422


def test_kill_rejects_a_protected_process(auth_client, monkeypatch):
    from app.metrics import processes as processes_module

    class FakeProc:
        def oneshot(self):
            from contextlib import nullcontext
            return nullcontext()

        def name(self):
            return "systemd"

        def username(self):
            return "root"

        def uids(self):
            class U:
                real = 0
            return U()

    monkeypatch.setattr(processes_module.psutil, "Process", lambda pid: FakeProc())
    response = auth_client.delete("/api/processes/4242")
    assert response.status_code == 403
    assert "protegidos" in response.json()["detail"]


def test_websocket_requires_a_session(client):
    from starlette.websockets import WebSocketDisconnect

    client.cookies.clear()
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws") as socket:
            socket.receive_json()
    assert excinfo.value.code == 4401


def test_websocket_delivers_the_subscribed_channels(auth_client):
    with auth_client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "hello"
        socket.send_json({"action": "subscribe", "channels": ["cpu", "memory", "inventado"]})

        confirmation = socket.receive_json()
        assert confirmation["type"] == "subscribed"
        assert set(confirmation["data"]["channels"]) == {"cpu", "memory"}
        # Un canal inexistente se ignora explicitamente en vez de fallar callando.
        assert confirmation["data"]["ignored"] == ["inventado"]

        received = set()
        for _ in range(4):
            message = socket.receive_json()
            if message["type"] == "metrics":
                received.add(message["channel"])
            if {"cpu", "memory"} <= received:
                break
        assert {"cpu", "memory"} <= received
