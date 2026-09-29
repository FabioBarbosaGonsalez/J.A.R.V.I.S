"""Configuração da aplicação, lida do arquivo `.env` via Pydantic Settings.

Segredos usam `SecretStr`: o valor não aparece em `repr()`, `print()` nem logs,
só quando alguém chama `.get_secret_value()` de propósito.
"""

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
PORTFOLIO_FILE = DATA_DIR / "carteira.csv"
CACHE_FILE = DATA_DIR / "cache.sqlite3"

# O servidor só aceita conexões da própria máquina. Não é configurável de propósito.
HOST = "127.0.0.1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # "CANVAS_TOKEN=" (vazio) conta como não configurado, e não como token ""
        env_ignore_empty=True,
    )

    # Geral
    assistant_name: str = "J.A.R.V.I.S"
    # Como o assistente chama você: um nome ou um tratamento formal ("senhor", "senhora")
    user_name: str = ""
    port: int = 8000
    timezone: str = "America/Sao_Paulo"
    refresh_seconds: int = 300
    demo_mode: bool = True

    # Canvas (Fase 2)
    canvas_base_url: str = "https://puc-campinas.instructure.com"
    canvas_token: SecretStr | None = None
    canvas_ics_url: SecretStr | None = None

    # Investimentos (Fase 2)
    brapi_token: SecretStr | None = None
    # Plano gratuito da brapi: 1 ativo por requisição (Startup: 10; Pro: 20).
    # A cota restante vem da própria brapi, em cada resposta.
    brapi_tickers_per_request: int = Field(default=1, ge=1, le=20)

    # Aba privada "Minha carteira": sem chave, a aba fica desativada
    portfolio_access_key: SecretStr | None = None
    private_session_minutes: int = Field(default=5, ge=1, le=120)

    # Google (Fase 3)
    google_credentials_file: str = "credentials.json"
    google_token_file: str = "token.json"

    # IA (Fase 4)
    gemini_api_key: SecretStr | None = None
    gemini_model: str = ""

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def secret(value: SecretStr | None) -> str:
    """Valor de um segredo, ou "" se não estiver configurado. Use só na hora de chamar a API."""
    return value.get_secret_value().strip() if value else ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
