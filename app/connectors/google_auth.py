"""Conexão com o Google (Gmail e Agenda) por OAuth 2.0, credencial do tipo "Desktop app".

- Escopos só de leitura: `gmail.readonly` e `calendar.readonly`. Mesmo que o
  código tentasse, o Google recusaria enviar e-mail ou criar evento.
- O login roda na sua máquina: o botão "Conectar Google" abre o consentimento
  no seu navegador, e o Google devolve a autorização para um servidor
  temporário em `localhost` (o fluxo padrão de apps desktop).
- O token (com o refresh token) fica num arquivo local, fora do Git. O access
  token vale cerca de 1 hora e é renovado sozinho.
- Com o app em modo "Testing" no Google Cloud, o refresh token expira em
  7 dias. Nesse caso os painéis pedem "Reconectar Google", sem quebrar nada.

As mensagens daqui aparecem na interface: nada de nomes de arquivo.
"""

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from app.connectors.http import ConnectorError
from app.models import PanelResponse

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]
LOGIN_TIMEOUT = 300  # segundos para concluir a autorização no navegador

log = logging.getLogger(__name__)

MESSAGES = {
    "not_configured": "Google não configurado: falta a credencial do aplicativo no Google Cloud.",
    "disconnected": "Google não conectado. Autorize o acesso somente leitura ao Gmail e à Agenda.",
    "connecting": "Aguardando a autorização no navegador…",
    "expired": "A conexão com o Google expirou (com o app em modo de teste, isso acontece a cada 7 dias). "
               "Reconecte para continuar.",
    "invalid": "A conexão salva com o Google não é válida. Conecte de novo.",
    "failed": "Não foi possível conectar ao Google: autorização cancelada, recusada ou tempo esgotado.",
}


class GoogleNotReady(Exception):
    """O Google não pode ser usado agora. `state` diz por quê."""

    def __init__(self, state: str, message: str):
        super().__init__(message)
        self.state = state
        self.message = message


@dataclass
class GoogleStatus:
    state: str  # not_configured | disconnected | connecting | connected | expired | error
    message: str | None = None


def run_browser_flow(credentials_path: Path) -> Credentials:
    """Abre o consentimento do Google no navegador e espera a resposta em localhost."""
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    return flow.run_local_server(
        port=0,  # porta livre qualquer; credenciais "Desktop app" aceitam
        open_browser=True,
        timeout_seconds=LOGIN_TIMEOUT,
        authorization_prompt_message="",
        success_message="Conectado ao Google. Pode fechar esta aba e voltar ao painel.",
        prompt="consent",  # garante um refresh token novo a cada conexão
    )


class GoogleAuth:
    def __init__(self, credentials_path: Path, token_path: Path,
                 run_flow: Callable[[Path], Credentials] = run_browser_flow):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._run_flow = run_flow
        self._lock = threading.RLock()
        self._connecting = False
        self._failed = False  # a última tentativa de conectar falhou

    # --- Credenciais ---------------------------------------------------------

    def credentials(self) -> Credentials:
        """Credenciais válidas (renova se preciso) ou `GoogleNotReady`."""
        with self._lock:
            if not self.credentials_path.exists():
                raise GoogleNotReady("not_configured", MESSAGES["not_configured"])
            if self._connecting:
                raise GoogleNotReady("connecting", MESSAGES["connecting"])
            if not self.token_path.exists():
                state = "error" if self._failed else "disconnected"
                raise GoogleNotReady(state, MESSAGES["failed" if self._failed else "disconnected"])
            try:
                creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
            except (ValueError, KeyError, json.JSONDecodeError):
                raise GoogleNotReady("disconnected", MESSAGES["invalid"]) from None

            if creds.valid:
                return creds
            if not creds.refresh_token:
                raise GoogleNotReady("expired", MESSAGES["expired"])
            try:
                creds.refresh(Request())
            except RefreshError:
                raise GoogleNotReady("expired", MESSAGES["expired"]) from None
            except TransportError:
                raise ConnectorError("Sem conexão com o Google.") from None
            self._save(creds)
            return creds

    def _save(self, creds: Credentials) -> None:
        self.token_path.write_text(creds.to_json(), encoding="utf-8")

    def mark_rejected(self) -> None:
        """O Google recusou o token (ex.: acesso revogado): esquece a conexão salva."""
        with self._lock:
            self.token_path.unlink(missing_ok=True)

    # --- Estado e conexão ------------------------------------------------------

    def status(self) -> GoogleStatus:
        try:
            self.credentials()
        except GoogleNotReady as exc:
            return GoogleStatus(exc.state, exc.message)
        except ConnectorError as exc:
            return GoogleStatus("error", str(exc))
        return GoogleStatus("connected")

    def start_connect(self) -> GoogleStatus:
        """Abre o consentimento no navegador, em segundo plano."""
        with self._lock:
            if not self.credentials_path.exists():
                return GoogleStatus("not_configured", MESSAGES["not_configured"])
            if self._connecting:
                return GoogleStatus("connecting", MESSAGES["connecting"])
            self._connecting = True
            self._failed = False
        threading.Thread(target=self._connect, name="google-login", daemon=True).start()
        return GoogleStatus("connecting", MESSAGES["connecting"])

    def _connect(self) -> None:
        try:
            creds = self._run_flow(self.credentials_path)
            with self._lock:
                self._save(creds)
        except Exception as exc:  # recusou, fechou a aba, tempo esgotado, rede...
            log.warning("Conexão com o Google não concluída (%s).", type(exc).__name__)
            with self._lock:
                self._failed = True
        finally:
            with self._lock:
                self._connecting = False


def not_ready_response(exc: GoogleNotReady, now: datetime) -> PanelResponse:
    """Painel de e-mails/agenda quando o Google não está pronto: explica e oferece o botão."""
    action = {
        "disconnected": "google_connect",
        "error": "google_connect",
        "expired": "google_reconnect",
        "connecting": "google_waiting",  # sem botão: só o título "Conectando"
    }.get(exc.state)
    return PanelResponse(status="not_configured", source="live", updated_at=now, message=exc.message, action=action)
