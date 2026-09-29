import pytest

from tests.conftest import make_settings
from app.config import get_settings
from app.main import app

PANEL_ROUTES = ["/api/emails", "/api/calendar", "/api/canvas", "/api/portfolio", "/api/briefing"]


def test_index_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert 'id="core"' in res.text


def test_javascript_served_as_module_mime(client):
    res = client.get("/static/js/app.js")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/javascript")


def test_status_uses_configured_name(client):
    body = client.get("/api/status").json()
    assert body["assistant_name"] == "TESTE"
    assert body["demo_mode"] is True


@pytest.mark.parametrize("route", PANEL_ROUTES)
def test_panels_ok_in_demo_mode(client, route):
    body = client.get(route).json()
    assert body["status"] == "ok"
    assert body["source"] == "demo"
    assert body["data"]


@pytest.mark.parametrize("route", PANEL_ROUTES)
@pytest.mark.parametrize("state", ["error", "not_configured"])
def test_simulated_states(client, route, state):
    body = client.get(route, params={"simulate": state}).json()
    assert body["status"] == state
    assert body["data"] is None
    assert body["message"]


def test_panels_not_configured_outside_demo_mode(client):
    app.dependency_overrides[get_settings] = lambda: make_settings(demo_mode=False)
    body = client.get("/api/canvas").json()
    assert body["status"] == "not_configured"


def test_canvas_sorted_and_urgent_flag(client):
    items = client.get("/api/canvas").json()["data"]
    due_dates = [d["due_at"] for d in items]
    assert due_dates == sorted(due_dates)
    urgent = [d for d in items if d["urgent"]]
    assert urgent, "o demo tem uma entrega pendente em menos de 48 h"
    assert all(d["status"] == "pending" and d["hours_left"] < 48 for d in urgent)
    # entregue não é urgente, mesmo com prazo curto
    assert not any(d["urgent"] for d in items if d["status"] == "submitted")


def test_briefing_crosses_sources(client):
    briefing = client.get("/api/briefing").json()["data"]
    assert "Banco de Dados" in briefing["text"]
    assert "Ricardo Almeida" in briefing["text"]  # e-mail do professor sobre a mesma disciplina
    assert any(h["level"] == "critical" for h in briefing["highlights"])


def test_chat_demo_reply(client):
    res = client.post("/api/chat", json={"message": "quais são minhas entregas?"})
    assert res.status_code == 200
    assert "Projeto final" in res.json()["reply"]


def test_chat_refuses_investment_advice(client):
    reply = client.post("/api/chat", json={"message": "devo comprar PETR4?"}).json()["reply"]
    assert "não faço recomendações" in reply


def test_chat_rejects_empty_message(client):
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_rejects_non_local_host(client):
    res = client.get("/api/status", headers={"host": "evil.example"})
    assert res.status_code == 400


def test_rejects_cross_origin_post(client):
    res = client.post("/api/chat", json={"message": "oi"}, headers={"origin": "https://evil.example"})
    assert res.status_code == 403


def test_allows_same_origin_post(client):
    res = client.post("/api/chat", json={"message": "oi"}, headers={"origin": "http://127.0.0.1:8000"})
    assert res.status_code == 200
