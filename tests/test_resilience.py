"""Acabamento: erros inesperados ficam contidos, logs sem segredos e inicialização amigável."""

import logging
import socket

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import __main__ as launcher
from app import sources
from app.config import HOST, Settings, get_settings
from app.llm import provider as llm
from app.logs import SecretRedactor, configured_secrets, setup_logging
from app.main import UNEXPECTED, app
from tests.conftest import make_settings


def boom(*args, **kwargs):
    raise RuntimeError("bug simulado")


# --- Erros inesperados ------------------------------------------------------------

def test_a_broken_panel_does_not_break_the_others(client, monkeypatch):
    monkeypatch.setattr(sources, "emails_panel", boom)

    broken = client.get("/api/emails").json()
    fine = client.get("/api/calendar").json()

    assert broken["status"] == "error" and broken["message"] == UNEXPECTED
    assert fine["status"] == "ok"


def test_briefing_survives_a_bug_in_the_ai_path(client, monkeypatch):
    monkeypatch.setattr(llm, "get_provider", lambda settings: object())
    monkeypatch.setattr("app.main.build_ai_briefing", boom)

    body = client.get("/api/briefing").json()

    assert body["status"] == "ok" and body["data"]["generator"] == "rules"
    assert "Resumo gerado por regras" in body["message"]


def test_chat_survives_a_bug_in_the_ai_path(client, monkeypatch):
    monkeypatch.setattr(llm, "get_provider", lambda settings: object())
    monkeypatch.setattr("app.main.ai_reply", boom)

    body = client.post("/api/chat", json={"message": "quais são minhas entregas?"}).json()

    assert body["generator"] == "rules" and "Projeto final" in body["reply"]
    assert "regras básicas" in body["notice"]


def test_other_routes_answer_with_a_short_message(settings, monkeypatch, caplog):
    monkeypatch.setattr(sources, "snapshot", boom)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False) as c:
            res = c.post("/api/chat", json={"message": "oi"})
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 500
    assert res.json() == {"detail": UNEXPECTED}
    assert "bug simulado" not in res.text  # o detalhe fica só no terminal
    assert any("bug simulado" in (r.exc_text or str(r.exc_info)) for r in caplog.records)


# --- Logs sem segredos -------------------------------------------------------------

SECRETS = dict(
    canvas_token="canvas-token-123", canvas_ics_url="https://canvas/feed/segredo-do-feed",
    brapi_token="brapi-abcdef", portfolio_access_key="minha-chave-longa", gemini_api_key="AIzaChaveGemini",
)


def test_configured_secrets():
    found = configured_secrets(make_settings(**SECRETS))
    assert set(found) == set(SECRETS.values())
    # Vazios ou curtos demais não entram (trocariam pedaços comuns de texto)
    assert configured_secrets(make_settings(brapi_token="abc")) == []


def test_redactor_cleans_messages_arguments_and_tracebacks():
    redactor = SecretRedactor(configured_secrets(make_settings(**SECRETS)))
    logger = logging.getLogger("teste.segredos")
    records = []

    class Keep(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    handler = Keep()
    handler.addFilter(redactor)
    logger.addHandler(handler)
    try:
        logger.warning("token %s e feed %s", "brapi-abcdef", "https://canvas/feed/segredo-do-feed")
        try:
            raise ValueError("falhou com AIzaChaveGemini")
        except ValueError:
            logger.exception("erro com minha-chave-longa")
    finally:
        logger.removeHandler(handler)

    text = "\n".join(records)
    for value in SECRETS.values():
        assert value not in text
    assert "***" in text and "Traceback" in text


def test_setup_logging_quiets_network_libraries(monkeypatch):
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", list(root.handlers))
    level = root.level
    try:
        setup_logging(make_settings(**SECRETS))
        assert logging.getLogger("httpx").level == logging.WARNING
        assert any(isinstance(f, SecretRedactor) for f in root.handlers[0].filters)
    finally:
        root.setLevel(level)


# --- Inicialização -------------------------------------------------------------------

def test_config_errors_never_show_the_value():
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None, port="porta-secreta", brapi_tickers_per_request=99)

    lines = launcher.config_errors(info.value)

    assert any(line.startswith("PORT:") for line in lines)
    assert any(line.startswith("BRAPI_TICKERS_PER_REQUEST:") for line in lines)
    assert "porta-secreta" not in " ".join(lines)


def test_invalid_env_exits_with_a_message(monkeypatch, capsys):
    def invalid():
        Settings(_env_file=None, port="x")

    monkeypatch.setattr(launcher, "get_settings", invalid)

    assert launcher.main([]) == 1
    assert "PORT" in capsys.readouterr().err


@pytest.fixture
def busy_port():
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        sock.listen()
        yield sock.getsockname()[1]


def test_port_in_use(busy_port):
    assert launcher.port_in_use(busy_port) is True


def test_busy_port_from_another_program(monkeypatch, capsys, busy_port):
    monkeypatch.setattr(launcher, "get_settings", lambda: make_settings(port=busy_port))
    monkeypatch.setattr(launcher.uvicorn, "run", boom)

    assert launcher.main([]) == 1
    assert "outro programa" in capsys.readouterr().err


def test_assistant_already_running_just_opens_it(monkeypatch, busy_port):
    opened = []
    monkeypatch.setattr(launcher, "get_settings", lambda: make_settings(port=busy_port))
    monkeypatch.setattr(launcher, "assistant_running", lambda port: True)
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)
    monkeypatch.setattr(launcher.uvicorn, "run", boom)

    assert launcher.main(["--open"]) == 0
    assert opened == [f"http://{HOST}:{busy_port}"]


def test_open_when_ready_waits_for_the_server(monkeypatch, busy_port):
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)

    launcher.open_when_ready("http://painel", busy_port, timeout=5).join(timeout=5)

    assert opened == ["http://painel"]


def test_config_errors_are_in_portuguese():
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None, port="x", demo_mode="talvez", gmail_max_messages=99, llm_provider="outro")

    lines = launcher.config_errors(info.value)

    assert "PORT: deve ser um número inteiro" in lines
    assert "DEMO_MODE: deve ser true ou false" in lines
    assert "GMAIL_MAX_MESSAGES: deve ser no máximo 50" in lines
    assert any(line.startswith("LLM_PROVIDER: valores aceitos") for line in lines)
