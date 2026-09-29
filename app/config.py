"""Configuração da aplicação, lida do arquivo `.env` via Pydantic Settings.

Segredos usam `SecretStr`: o valor não aparece em `repr()`, `print()` nem logs,
só quando alguém chama `.get_secret_value()` de propósito.
"""

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"

# O servidor só aceita conexões da própria máquina. Não é configurável de propósito.
HOST = "127.0.0.1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
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

    # Google (Fase 3)
    google_credentials_file: str = "credentials.json"
    google_token_file: str = "token.json"

    # IA (Fase 4)
    gemini_api_key: SecretStr | None = None
    gemini_model: str = ""

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
