"""Aba privada "Minha carteira": chave de acesso e sessões.

- A chave fica no .env (PORTFOLIO_ACCESS_KEY) e é conferida só no servidor,
  com comparação em tempo constante (`hmac.compare_digest`).
- Ao acertar, o servidor cria uma sessão aleatória e a entrega num cookie
  HttpOnly (o JavaScript não consegue lê-lo) e SameSite=Strict (outros sites
  não conseguem usá-lo). A sessão vive só na memória do servidor: reiniciar
  o servidor bloqueia tudo.
- A sessão expira após alguns minutos sem uso.
- Erros seguidos fazem a espera crescer (5 s, 10 s, 20 s... até 5 minutos),
  o que torna inviável adivinhar a chave por tentativa e erro.
"""

import hmac
import secrets
import threading
import time
from dataclasses import dataclass

COOKIE_NAME = "jarvis_private"
COOKIE_PATH = "/api/private"
MIN_KEY_LENGTH = 10  # chave mais curta que isso deixa a aba desativada
FREE_ATTEMPTS = 3  # erros sem espera
BASE_DELAY = 5  # segundos, dobra a cada erro depois dos livres
MAX_DELAY = 300


def key_problem(key: str) -> str | None:
    """Por que a chave configurada não serve (texto para a interface), ou None se serve.

    As mensagens não citam arquivos nem variáveis: os detalhes de configuração
    aparecem só no terminal, ao iniciar o servidor.
    """
    if not key:
        return "Aba desativada: nenhuma chave de acesso configurada."
    if len(key) < MIN_KEY_LENGTH:
        return f"Aba desativada: a chave de acesso precisa ter {MIN_KEY_LENGTH} caracteres ou mais."
    return None


@dataclass
class UnlockResult:
    ok: bool
    token: str | None = None
    retry_after: int = 0  # segundos até poder tentar de novo


class PrivateSessions:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._sessions: dict[str, float] = {}  # token -> último uso
        self._failures = 0
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    def unlock(self, attempt: str, key: str) -> UnlockResult:
        with self._lock:
            now = self._clock()
            if now < self._blocked_until:
                return UnlockResult(ok=False, retry_after=int(self._blocked_until - now) + 1)

            if hmac.compare_digest(attempt.encode("utf-8"), key.encode("utf-8")):
                self._failures = 0
                token = secrets.token_urlsafe(32)
                self._sessions[token] = now
                return UnlockResult(ok=True, token=token)

            self._failures += 1
            if self._failures >= FREE_ATTEMPTS:
                delay = min(BASE_DELAY * 2 ** (self._failures - FREE_ATTEMPTS), MAX_DELAY)
                self._blocked_until = now + delay
                return UnlockResult(ok=False, retry_after=delay)
            return UnlockResult(ok=False)

    def check(self, token: str | None, timeout_seconds: float) -> bool:
        """Sessão válida? Cada uso renova o prazo de inatividade."""
        if not token:
            return False
        with self._lock:
            now = self._clock()
            # Limpa sessões vencidas
            for t, last in list(self._sessions.items()):
                if now - last > timeout_seconds:
                    del self._sessions[t]
            if token not in self._sessions:
                return False
            self._sessions[token] = now
            return True

    def lock(self, token: str | None) -> None:
        with self._lock:
            self._sessions.pop(token or "", None)


sessions = PrivateSessions()
