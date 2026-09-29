import httpx
import pytest
from fastapi.testclient import TestClient

from app import sources
from app.cache import Cache
from app.config import Settings, get_settings
from app.connectors.http import read_only_client
from app.main import app


def make_settings(**overrides) -> Settings:
    # _env_file=None: os testes não dependem do seu .env
    return Settings(_env_file=None, **overrides)


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"Teste tentou acessar a rede: {request.url.host}")


@pytest.fixture(autouse=True)
def isolated_sources(tmp_path, monkeypatch):
    """Cache temporário e nenhuma chamada de rede real em nenhum teste."""
    monkeypatch.setattr(sources, "get_cache", lambda: Cache(tmp_path / "cache.sqlite3"))
    monkeypatch.setattr(sources, "get_http", lambda: read_only_client(transport=httpx.MockTransport(_no_network)))


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
