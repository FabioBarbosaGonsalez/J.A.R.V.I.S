"""Logs do terminal: legíveis e sem segredos.

- Formato curto, com hora e origem.
- Bibliotecas de rede (httpx, Google) só registram avisos: no nível INFO, o
  httpx escreveria cada URL acessada, e o link do feed iCal contém um segredo.
- `SecretRedactor` troca por "***" qualquer chave ou token configurado que
  apareça numa mensagem de log, inclusive em tracebacks. É uma segunda
  barreira: o código já evita registrar segredos.
"""

import logging

from app.config import Settings, secret

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
QUIET_LOGGERS = ("httpx", "httpcore", "google_genai", "google.auth", "urllib3", "googleapiclient")
MIN_SECRET_LENGTH = 6  # valores curtos demais trocariam pedaços comuns de texto


def configured_secrets(settings: Settings) -> list[str]:
    values = [
        secret(settings.canvas_token),
        secret(settings.canvas_ics_url),
        secret(settings.brapi_token),
        secret(settings.portfolio_access_key),
        secret(settings.gemini_api_key),
    ]
    # Os mais longos primeiro: um segredo pode conter outro
    return sorted({v for v in values if len(v) >= MIN_SECRET_LENGTH}, key=len, reverse=True)


class SecretRedactor(logging.Filter):
    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = secrets

    def _clean(self, text: str) -> str:
        for value in self.secrets:
            text = text.replace(value, "***")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.secrets:
            return True
        # Resolve a mensagem agora, para limpar também os argumentos
        record.msg = self._clean(record.getMessage())
        record.args = None
        if record.exc_info:
            # O traceback formatado também passa pela limpeza
            formatter = logging.Formatter()
            record.exc_text = self._clean(formatter.formatException(record.exc_info))
            record.exc_info = None
        if record.stack_info:
            record.stack_info = self._clean(record.stack_info)
        return True


def setup_logging(settings: Settings, level: int = logging.INFO) -> SecretRedactor:
    """Configura o log do terminal. Chame uma vez, ao iniciar o servidor."""
    redactor = SecretRedactor(configured_secrets(settings))
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(FORMAT, datefmt="%H:%M:%S"))
    handler.addFilter(redactor)

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    # Os logs do uvicorn passam pelo mesmo filtro (ex.: uma URL de acesso com segredo)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers[:] = []
        logger.propagate = True
    return redactor
