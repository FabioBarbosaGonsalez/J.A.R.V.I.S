"""Gmail: as últimas mensagens da caixa de entrada (somente leitura).

Para cada mensagem pedimos só os metadados (remetente, assunto) e o trecho que
o próprio Gmail gera; o corpo dos e-mails nunca é baixado. As buscas das
mensagens rodam em paralelo para o painel abrir rápido.
"""

import html
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.header import decode_header, make_header
from email.utils import parseaddr

import httpx

from app.cache import Cache
from app.config import Settings
from app.connectors.google_auth import MESSAGES, GoogleAuth, GoogleNotReady, not_ready_response
from app.connectors.http import ConnectorError, get
from app.models import Email, PanelResponse

API = "https://gmail.googleapis.com/gmail/v1/users/me"
CACHE_KEY = "gmail:inbox"
TTL = 2 * 60
MIN_FORCE_INTERVAL = 30
WORKERS = 6

ERRORS = {
    401: "O Google recusou a conexão.",
    403: "O Google negou o acesso ao Gmail. Confira se a API do Gmail está ativada no seu projeto do Google Cloud.",
}

_lock = threading.Lock()


def load(settings: Settings, cache: Cache, http: httpx.Client, auth: GoogleAuth,
         force: bool = False) -> PanelResponse[list[Email]]:
    now = datetime.now(settings.tz)
    with _lock:
        cached = cache.get_stale(CACHE_KEY)
        if cached and (time.time() - cached.stored_at < MIN_FORCE_INTERVAL if force else cached.fresh):
            return _from_cache(cached, settings)

        try:
            creds = auth.credentials()
        except GoogleNotReady as exc:
            return not_ready_response(exc, now)
        except ConnectorError as exc:
            return _stale_or_error(cached, str(exc), settings, now)

        try:
            emails = _fetch(http, creds.token, settings)
        except ConnectorError as exc:
            if exc.status == 401:
                auth.mark_rejected()
                return not_ready_response(GoogleNotReady("expired", MESSAGES["expired"]), now)
            return _stale_or_error(cached, str(exc), settings, now)

        cache.set(CACHE_KEY, [e.model_dump(mode="json") for e in emails], TTL)
        return PanelResponse(status="ok", source="live", updated_at=now, data=emails)


def _from_cache(entry, settings: Settings) -> PanelResponse[list[Email]]:
    return PanelResponse(
        status="ok", source="cache", updated_at=datetime.fromtimestamp(entry.stored_at, settings.tz),
        data=[Email(**e) for e in entry.value],
    )


def _stale_or_error(cached, reason: str, settings: Settings, now: datetime) -> PanelResponse[list[Email]]:
    if cached:
        stale = _from_cache(cached, settings)
        stale.message = f"{reason} Mostrando os e-mails de {stale.updated_at:%H:%M}."
        return stale
    return PanelResponse(status="error", source="live", updated_at=now, message=reason)


def _fetch(http: httpx.Client, token: str, settings: Settings) -> list[Email]:
    headers = {"Authorization": f"Bearer {token}"}
    listing = get(http, f"{API}/messages", what="o Gmail", status_messages=ERRORS, headers=headers,
                  params={"labelIds": "INBOX", "maxResults": settings.gmail_max_messages}).json()
    ids = [m["id"] for m in listing.get("messages", [])]

    def fetch_one(message_id: str) -> dict:
        return get(http, f"{API}/messages/{message_id}", what="o Gmail", status_messages=ERRORS, headers=headers,
                   params=[("format", "metadata"), ("metadataHeaders", "From"), ("metadataHeaders", "Subject")]).json()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        messages = list(pool.map(fetch_one, ids))
    domains = [d.strip().lower() for d in settings.university_email_domains.split(",") if d.strip()]
    emails = [parse_message(m, settings, domains) for m in messages]
    return sorted(emails, key=lambda e: e.received_at, reverse=True)


def _decode(value: str) -> str:
    """Cabeçalhos podem vir codificados ("=?UTF-8?B?...?=")."""
    try:
        return str(make_header(decode_header(value)))
    except (ValueError, LookupError):
        return value


def parse_message(message: dict, settings: Settings, university_domains: list[str]) -> Email:
    headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
    name, address = parseaddr(_decode(headers.get("from", "")))
    domain = address.rpartition("@")[2].lower()
    return Email(
        id=message["id"],
        sender_name=name or address or "(sem remetente)",
        sender_email=address,
        subject=_decode(headers.get("subject", "")).strip() or "(sem assunto)",
        snippet=html.unescape(message.get("snippet", "")),
        received_at=datetime.fromtimestamp(int(message["internalDate"]) / 1000, settings.tz),
        unread="UNREAD" in message.get("labelIds", []),
        from_university=any(domain == d or domain.endswith("." + d) for d in university_domains),
    )
