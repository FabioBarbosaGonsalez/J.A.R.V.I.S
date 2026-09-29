"""Aba privada "Minha carteira": chave, sessão, espera crescente e bloqueio."""

import pytest

from app import private
from app.config import get_settings
from app.main import app
from app.private import PrivateSessions
from tests.conftest import make_settings

KEY = "chave-de-teste-123"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# --- Sessões -------------------------------------------------------------------

def test_right_key_opens_a_session():
    s = PrivateSessions()
    result = s.unlock(KEY, KEY)
    assert result.ok and len(result.token) >= 32
    assert s.check(result.token, 60)
    assert not s.check("token-inventado", 60)
    assert not s.check(None, 60)


def test_session_expires_after_inactivity_and_renews_on_use():
    clock = Clock()
    s = PrivateSessions(clock)
    token = s.unlock(KEY, KEY).token
    clock.now += 50
    assert s.check(token, 60)  # usou: renova
    clock.now += 50
    assert s.check(token, 60)
    clock.now += 61
    assert not s.check(token, 60)


def test_lock_ends_the_session():
    s = PrivateSessions()
    token = s.unlock(KEY, KEY).token
    s.lock(token)
    assert not s.check(token, 60)


def test_wrong_attempts_make_the_wait_grow():
    clock = Clock()
    s = PrivateSessions(clock)
    assert [s.unlock("errada", KEY).retry_after for _ in range(2)] == [0, 0]  # 2 erros livres
    assert s.unlock("errada", KEY).retry_after == 5  # 3º erro: 5 s
    blocked = s.unlock(KEY, KEY)  # nem a chave certa passa durante a espera
    assert not blocked.ok and blocked.retry_after > 0
    clock.now += 6
    assert s.unlock("errada", KEY).retry_after == 10  # dobra
    clock.now += 11
    assert s.unlock(KEY, KEY).ok  # acertou: zera
    assert s.unlock("errada", KEY).retry_after == 0


def test_wait_has_a_ceiling():
    clock = Clock()
    s = PrivateSessions(clock)
    for _ in range(20):
        result = s.unlock("errada", KEY)
        clock.now += result.retry_after + 1
    assert result.retry_after == private.MAX_DELAY


@pytest.mark.parametrize("key, problem", [
    ("", "nenhuma chave"),
    ("123456789", "10 caracteres ou mais"),
    ("1234567890", None),
])
def test_key_needs_at_least_ten_characters(key, problem):
    result = private.key_problem(key)
    assert (result is None) if problem is None else (problem in result)


# --- Rotas ---------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fresh_sessions(monkeypatch):
    monkeypatch.setattr(private, "sessions", PrivateSessions())


@pytest.fixture
def with_key(client):
    app.dependency_overrides[get_settings] = lambda: make_settings(demo_mode=True, portfolio_access_key=KEY)
    return client


def test_disabled_without_key(client):
    assert client.get("/api/private/status").json()["enabled"] is False
    assert client.post("/api/private/unlock", json={"key": "qualquer"}).status_code == 403
    assert client.get("/api/private/portfolio").status_code == 403


@pytest.mark.parametrize("key", ["curta", "123456789"])  # menos de 10 caracteres
def test_short_key_disables_the_tab(client, key):
    app.dependency_overrides[get_settings] = lambda: make_settings(demo_mode=True, portfolio_access_key=key)
    status = client.get("/api/private/status").json()
    assert status["enabled"] is False and status["unlocked"] is False
    assert "10 caracteres ou mais" in status["message"]
    assert client.post("/api/private/unlock", json={"key": key}).status_code == 403  # nem a própria chave curta
    assert client.get("/api/private/portfolio").status_code == 403


def test_ten_characters_is_enough(client):
    app.dependency_overrides[get_settings] = lambda: make_settings(demo_mode=True, portfolio_access_key="1234567890")
    assert client.get("/api/private/status").json()["enabled"] is True
    assert client.post("/api/private/unlock", json={"key": "1234567890"}).status_code == 200


def test_public_portfolio_route_no_longer_exists(with_key):
    assert with_key.get("/api/portfolio").status_code == 404


def test_portfolio_requires_unlock(with_key):
    assert with_key.get("/api/private/portfolio").status_code == 401
    assert with_key.get("/api/private/status").json() == {
        "enabled": True, "unlocked": False, "session_minutes": 5, "message": None}


def test_unlock_sets_a_protected_cookie_and_opens_the_portfolio(with_key):
    res = with_key.post("/api/private/unlock", json={"key": KEY})
    assert res.status_code == 200
    cookie = res.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/api/private" in cookie
    assert KEY not in cookie
    assert res.headers["cache-control"] == "no-store"

    portfolio = with_key.get("/api/private/portfolio")
    assert portfolio.status_code == 200
    assert portfolio.headers["cache-control"] == "no-store"
    assert portfolio.json()["data"]["total_value"] > 0
    assert with_key.get("/api/private/status").json()["unlocked"] is True


def test_lock_button(with_key):
    with_key.post("/api/private/unlock", json={"key": KEY})
    with_key.post("/api/private/lock")
    assert with_key.get("/api/private/portfolio").status_code == 401


def test_wrong_key_and_growing_wait(with_key):
    codes = [with_key.post("/api/private/unlock", json={"key": "errada"}).status_code for _ in range(3)]
    assert codes == [401, 401, 429]
    blocked = with_key.post("/api/private/unlock", json={"key": KEY})
    assert blocked.status_code == 429 and blocked.headers["retry-after"]


def test_other_sites_cannot_unlock(with_key):
    res = with_key.post("/api/private/unlock", json={"key": KEY}, headers={"origin": "https://evil.example"})
    assert res.status_code == 403
