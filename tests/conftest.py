import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app


def make_settings(**overrides) -> Settings:
    # _env_file=None: os testes não dependem do seu .env
    return Settings(_env_file=None, **overrides)


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
