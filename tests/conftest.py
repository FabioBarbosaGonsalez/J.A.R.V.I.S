import httpx
import pytest
from fastapi.testclient import TestClient

from app import actions, sources
from app.cache import Cache
from app.config import Settings, get_settings
from app.connectors.google_auth import GoogleAuth
from app.connectors.http import read_only_client
from app.llm import chat
from app.llm import provider as llm
from app.main import app


def make_settings(**overrides) -> Settings:
    # _env_file=None: os testes não dependem do seu .env
    return Settings(_env_file=None, **overrides)


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"Teste tentou acessar a rede: {request.url.host}")


def _no_browser(credentials_path):
    raise AssertionError("Teste tentou abrir o login do Google")


@pytest.fixture(autouse=True)
def isolated_sources(tmp_path, monkeypatch):
    """Cache temporário, nenhuma chamada de rede real e nenhum arquivo real do Google."""
    monkeypatch.setattr(sources, "get_cache", lambda: Cache(tmp_path / "cache.sqlite3"))
    monkeypatch.setattr(sources, "get_http", lambda: read_only_client(transport=httpx.MockTransport(_no_network)))
    google = GoogleAuth(tmp_path / "credentials.json", tmp_path / "token.json", run_flow=_no_browser)
    monkeypatch.setattr(sources, "get_google_auth", lambda settings: google)
    # IA desligada por padrão: nenhum teste gasta cota. Quem precisa usa um provedor falso.
    monkeypatch.setattr(llm, "get_provider", lambda settings: None)
    chat.memory.clear()
    # Ações: nenhuma proposta sobra de outro teste, e nada é gravado nos seus arquivos
    actions.store.clear()
    monkeypatch.setattr(actions, "HISTORY_FILE", tmp_path / "historico.jsonl")
    monkeypatch.setattr(sources, "PORTFOLIO_FILE", tmp_path / "carteira.csv")


@pytest.fixture
def settings() -> Settings:
    return make_settings(demo_mode=True, assistant_name="TESTE")


@pytest.fixture
def client(settings):
    app.dependency_overrides[get_settings] = lambda: settings
    # base_url local: o TrustedHostMiddleware recusa qualquer outro Host
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c
    app.dependency_overrides.clear()
