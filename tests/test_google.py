"""Gmail e Agenda com o Google simulado: conexão, leitura e expiração do token."""

import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from app import sources
from app.cache import Cache
from app.config import get_settings
from app.connectors import gcalendar, gmail
from app.connectors.google_auth import SCOPES, GoogleAuth
from app.connectors.http import read_only_client
from app.main import app
from tests.conftest import make_settings

TZ = "America/Sao_Paulo"
ACCESS = "access-token-simulado"


def write_token(path, expired=False):
    expiry = datetime.now(timezone.utc) + (timedelta(hours=-1) if expired else timedelta(hours=1))
    path.write_text(json.dumps({
        "token": ACCESS, "refresh_token": "refresh-simulado", "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "id", "client_secret": "segredo", "scopes": SCOPES,
        "expiry": expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }), encoding="utf-8")


@pytest.fixture
def paths(tmp_path):
    creds, token = tmp_path / "credentials.json", tmp_path / "token.json"
    creds.write_text('{"installed": {"client_id": "id", "client_secret": "segredo"}}', encoding="utf-8")
    return creds, token


def wait_login(auth):
    for _ in range(100):
        if auth.status().state != "connecting":
            return
        time.sleep(0.02)


# --- Estados da conexão ---------------------------------------------------------

def test_states(tmp_path, paths, monkeypatch):
    creds, token = paths
    assert GoogleAuth(tmp_path / "nada.json", token).status().state == "not_configured"
    auth = GoogleAuth(creds, token)
    assert auth.status().state == "disconnected"

    write_token(token)
    assert auth.status().state == "connected"

    write_token(token, expired=True)
    monkeypatch.setattr(Credentials, "refresh", lambda self, request: (_ for _ in ()).throw(
        RefreshError("invalid_grant: Token has been expired or revoked.")))
    status = auth.status()
    assert status.state == "expired" and "7 dias" in status.message


def test_expired_access_token_is_renewed_and_saved(paths, monkeypatch):
    creds, token = paths
    write_token(token, expired=True)

    def fake_refresh(self, request):
        self.token = "novo-access-token"
        self.expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)
    assert GoogleAuth(creds, token).credentials().token == "novo-access-token"
    assert json.loads(token.read_text(encoding="utf-8"))["token"] == "novo-access-token"


def test_browser_login_saves_the_token(paths):
    creds, token = paths

    def fake_flow(credentials_path):
        return Credentials(token=ACCESS, refresh_token="r", client_id="id", client_secret="s",
                           token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES,
                           expiry=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1))

    auth = GoogleAuth(creds, token, run_flow=fake_flow)
    assert auth.start_connect().state == "connecting"
    wait_login(auth)
    assert auth.status().state == "connected"
    assert token.exists()


def test_cancelled_login_offers_to_try_again(paths):
    creds, token = paths

    def cancelled(credentials_path):
        raise RuntimeError("usuário fechou a aba")

    auth = GoogleAuth(creds, token, run_flow=cancelled)
    auth.start_connect()
    wait_login(auth)
    status = auth.status()
    assert status.state == "error" and "cancelada" in status.message


def test_connect_without_app_credential(tmp_path):
    auth = GoogleAuth(tmp_path / "nada.json", tmp_path / "token.json")
    assert auth.start_connect().state == "not_configured"


# --- Gmail ----------------------------------------------------------------------

def gmail_message(mid, sender, subject, unread=True, minutes_ago=10):
    return {
        "id": mid, "labelIds": ["INBOX", "UNREAD"] if unread else ["INBOX"],
        "snippet": "Segue o material &amp; os exercícios &#39;extras&#39;",
        "internalDate": str(int((time.time() - minutes_ago * 60) * 1000)),
        "payload": {"headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}]},
    }


MESSAGES = {
    "a": gmail_message("a", "Prof. Ana <ana@puc-campinas.edu.br>", "Entrega do projeto", minutes_ago=5),
    "b": gmail_message("b", "Loja <ofertas@loja.example>", "=?UTF-8?B?UHJvbW/Dp8Ojbw==?=", unread=False, minutes_ago=60),
    "c": gmail_message("c", "Canvas <notificacoes@pucc.instructure.com>", "Nova nota", minutes_ago=30),
}


class FakeGoogle:
    def __init__(self, status=200, events=None):
        self.status = status
        self.events = events or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "erro"}})
        path = request.url.path
        if path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": i} for i in MESSAGES]})
        if "/messages/" in path:
            return httpx.Response(200, json=MESSAGES[path.rsplit("/", 1)[-1]])
        if path.endswith("/events"):
            calendar_id = path.split("/calendars/")[1].split("/")[0]
            return httpx.Response(200, json={"items": self.events.get(calendar_id, [])})
        return httpx.Response(404)


@pytest.fixture
def connected(paths):
    creds, token = paths
    write_token(token)
    return GoogleAuth(creds, token)


def run(module, fake, auth, tmp_path, **settings):
    s = make_settings(demo_mode=False, timezone=TZ, **settings)
    http = read_only_client(transport=httpx.MockTransport(fake))
    return module.load(s, Cache(tmp_path / "c.sqlite3"), http, auth)


def test_gmail_reads_inbox_metadata_only(connected, tmp_path):
    fake = FakeGoogle()
    res = run(gmail, fake, connected, tmp_path)

    assert res.status == "ok"
    assert [e.id for e in res.data] == ["a", "c", "b"]  # mais recentes primeiro
    ana, canvas_mail, shop = res.data
    assert (ana.sender_name, ana.sender_email, ana.unread, ana.from_university) == (
        "Prof. Ana", "ana@puc-campinas.edu.br", True, True)
    assert canvas_mail.from_university  # subdomínio de instructure.com
    assert (shop.subject, shop.unread, shop.from_university) == ("Promoção", False, False)
    assert ana.snippet == "Segue o material & os exercícios 'extras'"

    detail = [r for r in fake.requests if "/messages/" in r.url.path]
    assert all(r.url.params["format"] == "metadata" for r in detail)  # nunca o corpo
    assert all(r.headers["Authorization"] == f"Bearer {ACCESS}" for r in fake.requests)
    assert all(r.method == "GET" for r in fake.requests)


def test_rejected_token_asks_to_reconnect(connected, tmp_path):
    res = run(gmail, FakeGoogle(status=401), connected, tmp_path)
    assert res.status == "not_configured" and res.action == "google_reconnect"
    assert not connected.token_path.exists()  # conexão esquecida
    assert connected.status().state == "disconnected"


def test_api_disabled_in_google_cloud(connected, tmp_path):
    res = run(gmail, FakeGoogle(status=403), connected, tmp_path)
    assert res.status == "error" and "API do Gmail está ativada" in res.message


def test_not_connected_offers_the_button(paths, tmp_path):
    creds, token = paths
    res = run(gmail, FakeGoogle(), GoogleAuth(creds, token), tmp_path)
    assert res.status == "not_configured" and res.action == "google_connect"


def test_expired_session_offers_reconnect(paths, tmp_path, monkeypatch):
    creds, token = paths
    write_token(token, expired=True)
    monkeypatch.setattr(Credentials, "refresh", lambda self, r: (_ for _ in ()).throw(RefreshError("invalid_grant")))
    res = run(gcalendar, FakeGoogle(), GoogleAuth(creds, token), tmp_path)
    assert res.action == "google_reconnect" and "Reconecte" in res.message


# --- Agenda ---------------------------------------------------------------------

def test_calendar_events(connected, tmp_path):
    fake = FakeGoogle(events={
        "primary": [
            {"id": "1", "summary": "Aula", "location": " Bloco H15 ",
             "start": {"dateTime": "2026-09-30T08:00:00-03:00"}, "end": {"dateTime": "2026-09-30T11:30:00-03:00"}},
            {"id": "2", "summary": "Feriado", "start": {"date": "2026-10-12"}, "end": {"date": "2026-10-13"}},
            {"id": "3", "status": "cancelled", "start": {"dateTime": "2026-09-30T09:00:00-03:00"}},
            {"id": "4", "summary": "Recusei", "attendees": [{"self": True, "responseStatus": "declined"}],
             "start": {"dateTime": "2026-09-30T10:00:00-03:00"}, "end": {"dateTime": "2026-09-30T11:00:00-03:00"}},
        ],
        "grupo@group.calendar.google.com": [
            {"id": "5", "start": {"dateTime": "2026-09-30T07:00:00Z"}, "end": {"dateTime": "2026-09-30T08:00:00Z"}},
        ],
    })
    res = run(gcalendar, fake, connected, tmp_path, google_calendar_ids="primary, grupo@group.calendar.google.com")

    assert [e.id for e in res.data] == ["5", "1", "2"]  # por início; cancelado e recusado ficam fora
    utc_event, aula, holiday = res.data
    assert (aula.title, aula.location, aula.all_day, aula.start.hour) == ("Aula", "Bloco H15", False, 8)
    assert (utc_event.title, utc_event.start.hour) == ("(sem título)", 4)  # 07:00Z -> 04:00 em São Paulo
    assert (holiday.all_day, holiday.start.day, holiday.end.day) == (True, 12, 13)

    assert b"/calendars/grupo%40group.calendar.google.com/events" in fake.requests[1].url.raw_path  # id codificado
    params = fake.requests[0].url.params
    assert params["singleEvents"] == "true" and params["orderBy"] == "startTime"
    start, end = datetime.fromisoformat(params["timeMin"]), datetime.fromisoformat(params["timeMax"])
    assert (end - start).days == 8 and (start.hour, start.minute) == (0, 0)  # hoje + 7 dias


# --- Rotas ------------------------------------------------------------------------

def test_google_routes_in_demo_mode(client):
    assert client.get("/api/google/status").json()["state"] == "demo"
    assert client.post("/api/google/connect").json()["state"] == "demo"


def test_google_routes_live(client, paths, monkeypatch):
    creds, token = paths
    app.dependency_overrides[get_settings] = lambda: make_settings(demo_mode=False)
    flows = []
    auth = GoogleAuth(creds, token, run_flow=lambda p: flows.append(p) or (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(sources, "get_google_auth", lambda settings: auth)

    assert client.get("/api/google/status").json()["state"] == "disconnected"
    assert client.post("/api/google/connect").json()["state"] == "connecting"
    wait_login(auth)
    assert flows == [creds]
    assert client.post("/api/google/connect", headers={"origin": "https://evil.example"}).status_code == 403
