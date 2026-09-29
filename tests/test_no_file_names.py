"""Nada que chega ao navegador cita arquivos de configuração ou de dados.

Os nomes (.env, carteira.csv...) só aparecem no terminal, ao iniciar o servidor.
"""

import re

import pytest

from app.__main__ import setup_hints
from app.config import STATIC_DIR, get_settings
from app.main import app
from tests.conftest import make_settings

# Arquivos do projeto e variáveis de configuração
FORBIDDEN = re.compile(
    r"\.env\b|\.csv\b|\.sqlite|credentials\.json|token\.json|README|"
    r"CANVAS_TOKEN|CANVAS_ICS_URL|BRAPI_TOKEN|PORTFOLIO_ACCESS_KEY|DEMO_MODE",
)


@pytest.mark.parametrize("path", sorted(p for p in STATIC_DIR.rglob("*") if p.is_file()), ids=lambda p: p.name)
def test_front_end_files_have_no_file_names(path):
    assert not FORBIDDEN.findall(path.read_text(encoding="utf-8"))


def test_api_messages_have_no_file_names(client, monkeypatch, tmp_path):
    # Modo real sem nada configurado: todos os painéis explicam o que falta
    monkeypatch.setattr("app.sources.PORTFOLIO_FILE", tmp_path / "nao-existe.csv")
    app.dependency_overrides[get_settings] = lambda: make_settings(demo_mode=False, portfolio_access_key="curta")
    routes = ["/api/status", "/api/emails", "/api/calendar", "/api/canvas", "/api/market", "/api/briefing",
              "/api/private/status", "/api/private/portfolio", "/api/openapi.json"]
    for route in routes:
        assert not FORBIDDEN.findall(client.get(route).text), route
    unlock = client.post("/api/private/unlock", json={"key": "x"})
    assert not FORBIDDEN.findall(unlock.text)


def test_terminal_hints_do_name_the_files(monkeypatch, tmp_path):
    monkeypatch.setattr("app.__main__.PORTFOLIO_FILE", tmp_path / "nao-existe.csv")
    hints = " ".join(setup_hints(make_settings(demo_mode=False, portfolio_access_key="curta")))
    for expected in ("CANVAS_TOKEN", "BRAPI_TOKEN", "data/carteira.csv", "PORTFOLIO_ACCESS_KEY", "10 caracteres"):
        assert expected in hints


def test_terminal_hints_quiet_when_configured(monkeypatch, tmp_path):
    csv = tmp_path / "carteira.csv"
    csv.write_text("ticker,tipo,quantidade,preco_medio\n", encoding="utf-8")
    monkeypatch.setattr("app.__main__.PORTFOLIO_FILE", csv)
    settings = make_settings(demo_mode=False, canvas_token="t", brapi_token="b", portfolio_access_key="1234567890")
    assert setup_hints(settings) == []
