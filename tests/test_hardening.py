"""Protecciones especificas de un panel sin TLS expuesto en la LAN."""
from __future__ import annotations

import pytest

from app.core.hardening import HostCheckMiddleware, origin_is_same_site
from app.core.security import COOKIE_NAME, create_token, decode_token, revoke_token


class Headers(dict):
    """Sustituto minimo de las cabeceras de Starlette (acceso sin distinguir mayusculas)."""

    def get(self, key, default=None):
        return super().get(key.lower(), default)


# --------------------------------------------------------------- cabecera Host
@pytest.fixture
def host_check():
    return HostCheckMiddleware(app=None)


@pytest.mark.parametrize("hostname", [
    "192.168.1.50", "10.0.0.4", "127.0.0.1", "localhost",
    "raspberrypi.local", "pi.lan", "servidor.home",
])
def test_local_hosts_are_accepted(host_check, hostname):
    assert host_check.allowed(hostname)


@pytest.mark.parametrize("hostname", [
    "evil.com", "attacker.example.org", "systemmonitor.ngrok.io",
])
def test_public_domains_are_rejected(host_check, hostname):
    """Un DNS rebinding necesita un dominio; entrando por IP no hay nada que rebindear."""
    assert not host_check.allowed(hostname)


def test_host_check_rejects_over_http(client):
    client.cookies.clear()
    response = client.get("/health", headers={"Host": "evil.com"})
    assert response.status_code == 400
    assert "Host no permitido" in response.text


def test_host_check_allows_an_ip(client):
    client.cookies.clear()
    assert client.get("/health", headers={"Host": "192.168.1.50:8080"}).status_code == 200


# ------------------------------------------------------- Origin del WebSocket
def test_origin_matching_the_host_is_accepted():
    assert origin_is_same_site(Headers({
        "origin": "http://192.168.1.50:8080", "host": "192.168.1.50:8080"}))


def test_foreign_origin_is_rejected():
    """Los WebSockets no pasan por CORS: sin esto cualquier web abriria uno."""
    assert not origin_is_same_site(Headers({
        "origin": "http://evil.com", "host": "192.168.1.50:8080"}))


def test_origin_on_another_port_is_rejected():
    assert not origin_is_same_site(Headers({
        "origin": "http://192.168.1.50:9999", "host": "192.168.1.50:8080"}))


def test_missing_origin_is_accepted():
    """curl y los scripts no mandan Origin, y ya presentan cookie o token."""
    assert origin_is_same_site(Headers({"host": "192.168.1.50:8080"}))


def test_websocket_rejects_a_foreign_origin(auth_client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as excinfo, auth_client.websocket_connect(
            "/ws", headers={"Origin": "http://evil.com"}) as socket:
        socket.receive_json()
    assert excinfo.value.code == 4403


# ------------------------------------------------------------------- cabeceras
def test_security_headers_are_present(client):
    client.cookies.clear()
    headers = client.get("/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    # script-src 'self' es lo que impide que un XSS ejecute codigo inyectado.
    assert "script-src 'self'" in headers["content-security-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]


def test_login_page_has_no_inline_script(client):
    """La CSP bloquearia un <script> embebido, asi que no debe quedar ninguno."""
    client.cookies.clear()
    body = client.get("/login").text
    assert "/static/js/login.js" in body
    assert "<script type=\"module\">" not in body


# ------------------------------------------------------------------- revocacion
def test_logout_invalidates_the_token_server_side(client):
    client.cookies.clear()
    client.post("/api/login", json={"username": "tester", "password": "secreto-de-prueba"})
    token = client.cookies.get(COOKIE_NAME)
    assert decode_token(token) is not None

    client.post("/api/logout")
    # Borrar la cookie no basta: una copia del token no debe seguir sirviendo.
    assert decode_token(token) is None
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_revoking_one_token_leaves_others_valid():
    first, _ = create_token("tester")
    second, _ = create_token("tester")
    revoke_token(first)
    assert decode_token(first) is None
    assert decode_token(second) is not None
