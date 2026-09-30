"""Google Agenda: eventos de hoje e dos próximos 7 dias, e criação de eventos.

`singleEvents=true` expande os eventos recorrentes em ocorrências, já na ordem
de início. Eventos cancelados e os que você recusou ficam de fora.

Criar evento (`create_event`) só acontece depois do clique em Confirmar, e
sempre na agenda principal. Não existe código para editar nem apagar eventos,
e o cliente usado recusa qualquer outra operação.
"""

import threading
import time
from datetime import date, datetime, time as dtime, timedelta
from urllib.parse import quote

import httpx

from app.cache import Cache
from app.config import Settings
from app.connectors.google_auth import MESSAGES, GoogleAuth, GoogleNotReady, not_ready_response
from app.connectors.http import ConnectorError, get, send, single_write_client
from app.models import CalendarEvent, EventDraft, PanelResponse

API = "https://www.googleapis.com/calendar/v3/calendars"
INSERT_URL = f"{API}/primary/events"
CREATED_NOTE = "Criado pelo assistente pessoal, com a sua confirmação."
CACHE_KEY = "gcal:events"
TTL = 5 * 60
MIN_FORCE_INTERVAL = 30
DAYS_AHEAD = 7

ERRORS = {
    401: "O Google recusou a conexão.",
    403: "O Google negou o acesso à Agenda. Confira se a API do Google Calendar está ativada no seu projeto do Google Cloud.",
    404: "Uma das agendas configuradas não foi encontrada.",
}

_lock = threading.Lock()


def load(settings: Settings, cache: Cache, http: httpx.Client, auth: GoogleAuth,
         force: bool = False) -> PanelResponse[list[CalendarEvent]]:
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
            events = _fetch(http, creds.token, settings, now)
        except ConnectorError as exc:
            if exc.status == 401:
                auth.mark_rejected()
                return not_ready_response(GoogleNotReady("expired", MESSAGES["expired"]), now)
            return _stale_or_error(cached, str(exc), settings, now)

        cache.set(CACHE_KEY, [e.model_dump(mode="json") for e in events], TTL)
        return PanelResponse(status="ok", source="live", updated_at=now, data=events)


def _from_cache(entry, settings: Settings) -> PanelResponse[list[CalendarEvent]]:
    return PanelResponse(
        status="ok", source="cache", updated_at=datetime.fromtimestamp(entry.stored_at, settings.tz),
        data=[CalendarEvent(**e) for e in entry.value],
    )


def _stale_or_error(cached, reason: str, settings: Settings, now: datetime) -> PanelResponse[list[CalendarEvent]]:
    if cached:
        stale = _from_cache(cached, settings)
        stale.message = f"{reason} Mostrando a agenda de {stale.updated_at:%H:%M}."
        return stale
    return PanelResponse(status="error", source="live", updated_at=now, message=reason)


def _fetch(http: httpx.Client, token: str, settings: Settings, now: datetime) -> list[CalendarEvent]:
    start = datetime.combine(now.date(), dtime(0), tzinfo=settings.tz)
    params = {
        "timeMin": start.isoformat(),
        "timeMax": (start + timedelta(days=DAYS_AHEAD + 1)).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 100,
        "timeZone": settings.timezone,
    }
    events: dict[str, CalendarEvent] = {}
    for calendar_id in (c.strip() for c in settings.google_calendar_ids.split(",") if c.strip()):
        body = get(http, f"{API}/{quote(calendar_id, safe='')}/events", what="a Agenda do Google",
                   status_messages=ERRORS, headers={"Authorization": f"Bearer {token}"}, params=params).json()
        for item in body.get("items", []):
            event = parse_event(item, settings)
            if event:
                events[event.id] = event
    return sorted(events.values(), key=lambda e: (e.start, not e.all_day))


def parse_event(item: dict, settings: Settings) -> CalendarEvent | None:
    if item.get("status") == "cancelled":
        return None
    me = next((a for a in item.get("attendees", []) if a.get("self")), None)
    if me and me.get("responseStatus") == "declined":
        return None
    start, end = item.get("start", {}), item.get("end", {})
    try:
        if "dateTime" in start:
            begins = datetime.fromisoformat(start["dateTime"]).astimezone(settings.tz)
            ends = datetime.fromisoformat(end.get("dateTime", start["dateTime"])).astimezone(settings.tz)
            all_day = False
        else:
            # Dia inteiro: o Google usa datas, com o fim exclusivo (dia seguinte)
            begins = datetime.combine(date.fromisoformat(start["date"]), dtime(0), tzinfo=settings.tz)
            ends = datetime.combine(date.fromisoformat(end.get("date", start["date"])), dtime(0), tzinfo=settings.tz)
            all_day = True
    except (KeyError, ValueError):
        return None
    return CalendarEvent(
        id=item["id"],
        title=(item.get("summary") or "").strip() or "(sem título)",
        start=begins,
        end=ends,
        all_day=all_day,
        location=(item.get("location") or "").strip() or None,
    )


# --- Criar evento (só depois da confirmação) ----------------------------------

def event_body(draft: EventDraft, settings: Settings) -> dict:
    if draft.all_day:
        start = {"date": draft.start.date().isoformat()}
        end = {"date": draft.end.date().isoformat()}  # o Google usa o fim exclusivo
    else:
        start = {"dateTime": draft.start.isoformat(), "timeZone": settings.timezone}
        end = {"dateTime": draft.end.isoformat(), "timeZone": settings.timezone}
    return {"summary": draft.title, "start": start, "end": end, "description": CREATED_NOTE}


class EventNotSent(ConnectorError):
    """Falhou antes de enviar o pedido ao Google: com certeza nada foi criado."""


def create_event(draft: EventDraft, settings: Settings, cache: Cache, auth: GoogleAuth,
                 http: httpx.Client | None = None) -> CalendarEvent:
    """Cria o evento na agenda principal.

    Erros sobem como `GoogleNotReady` (conexão ou permissão), `EventNotSent`
    (nada saiu da máquina) ou `ConnectorError` (a resposta do Google).
    """
    try:
        creds = auth.credentials()
    except ConnectorError as exc:
        raise EventNotSent(str(exc)) from None
    if not auth.can_create_events():
        raise GoogleNotReady("needs_write", MESSAGES["needs_write"])

    client = http or single_write_client("POST", INSERT_URL)
    try:
        response = send(
            client, "POST", INSERT_URL, what="a Agenda do Google",
            status_messages={403: MESSAGES["needs_write"]},
            headers={"Authorization": f"Bearer {creds.token}"}, json=event_body(draft, settings),
        )
    except ConnectorError as exc:
        if exc.status == 401:
            auth.mark_rejected()
            raise GoogleNotReady("expired", MESSAGES["expired"]) from None
        if exc.status == 403:
            raise GoogleNotReady("needs_write", MESSAGES["needs_write"]) from None
        raise
    finally:
        if http is None:
            client.close()

    # O painel da agenda busca de novo na próxima atualização
    cache.delete(CACHE_KEY)
    created = parse_event(response.json(), settings)
    return created or CalendarEvent(id="", title=draft.title, start=draft.start, end=draft.end, all_day=draft.all_day)
