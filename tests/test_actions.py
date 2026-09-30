"""Ações com confirmação: a IA propõe, só o clique grava, uma vez e dentro do prazo."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import actions, sources
from app.config import get_settings
from app.connectors import gcalendar
from app.connectors.google_auth import GoogleNotReady
from app.connectors.http import ConnectorError, single_write_client
from app.llm import provider as llm
from app.llm.provider import Reply
from app.llm.tools import make_executor
from app.main import app
from app.models import AssetDraft, EventDraft
from tests.conftest import make_settings

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=TZ)  # terça-feira
KEY = "chave-de-teste-123"


def event_draft(**kw) -> EventDraft:
    start = kw.pop("start", datetime.now(TZ) + timedelta(days=1))
    return EventDraft(title=kw.pop("title", "Estudo de Cálculo"), start=start, end=start + timedelta(hours=1), **kw)


# --- Armazém de propostas ---------------------------------------------------------

def test_proposal_is_single_use():
    store = actions.ActionStore()
    proposal = store.propose(NOW, event=event_draft())

    assert store.get(proposal.id) is proposal
    assert store.take(proposal.id) is proposal
    assert store.take(proposal.id) is None
    assert store.get(proposal.id) is None


def test_proposal_expires():
    clock = [1000.0]
    store = actions.ActionStore(ttl=300, clock=lambda: clock[0])
    proposal = store.propose(NOW, event=event_draft())
    assert proposal.expires_at == NOW + timedelta(minutes=5)

    clock[0] += 299
    assert store.get(proposal.id) is proposal
    clock[0] += 2
    assert store.get(proposal.id) is None
    assert store.take(proposal.id) is None


def test_ids_are_unguessable_and_distinct():
    store = actions.ActionStore()
    ids = {store.propose(NOW, event=event_draft()).id for _ in range(50)}
    assert len(ids) == 50
    assert all(len(i) >= 20 for i in ids)


def test_asset_card_in_chat_has_no_numbers():
    draft = AssetDraft(ticker="MXRF11", asset_type="FII", quantity=10, price=9.8)
    card = actions.store.propose(NOW, asset=draft).card().model_dump_json()
    assert "MXRF11" in card
    assert "9.8" not in card and "quantity" not in card and "price" not in card


# --- Ferramentas de proposta -----------------------------------------------------

@pytest.fixture
def propose():
    cards = []
    execute = make_executor(make_settings(), NOW, cards)
    return cards, lambda name, **args: execute(name, args)


def test_propose_event_with_time(propose):
    cards, run = propose

    result = run("propor_evento", titulo="  Estudo  de Cálculo ", data="2026-09-30", hora_inicio="19h30")

    assert result["resultado"]["proposta_criada"] is True
    assert "Nada foi gravado" in result["resultado"]["aviso"]
    assert result["resultado"]["evento"] == "Estudo de Cálculo, quarta 30/09/2026 das 19:30 às 20:30"
    [card] = cards
    assert card.kind == "event"
    assert card.event.title == "Estudo de Cálculo"
    assert card.event.start == datetime(2026, 9, 30, 19, 30, tzinfo=TZ)
    assert card.event.duration_minutes == 60
    assert actions.store.get(card.id) is not None


def test_propose_all_day_event(propose):
    cards, run = propose

    run("propor_evento", titulo="Feriado", data="2026-10-12")

    event = cards[0].event
    assert event.all_day is True
    assert event.end - event.start == timedelta(days=1)


@pytest.mark.parametrize("args, error", [
    ({"titulo": "X", "data": "2026-09-28"}, "já passou"),
    ({"titulo": "X", "data": "2026-09-29", "hora_inicio": "08:00"}, "já passou"),
    ({"titulo": "X", "data": "2026-09-30", "hora_inicio": "25:00"}, "HH:MM"),
    ({"titulo": "X", "data": "2026-09-30", "hora_inicio": "19:00", "duracao_minutos": 2000}, "duracao_minutos"),
    ({"titulo": "", "data": "2026-09-30"}, "titulo"),
    ({"titulo": "X"}, "data"),
    ({"titulo": "X", "data": "2030-01-01"}, "longe demais"),
])
def test_propose_event_validation(propose, args, error):
    cards, run = propose
    assert error in run("propor_evento", **args)["erro"]
    assert cards == []


def test_propose_asset(propose):
    cards, run = propose

    result = run("propor_ativo", ticker="mxrf11", tipo="fii", quantidade=10, preco_medio=9.8)

    assert result["resultado"]["ativo"] == "MXRF11"
    assert "Não repita quantidade" in result["resultado"]["aviso"]
    proposal = actions.store.get(cards[0].id)
    assert proposal.asset == AssetDraft(ticker="MXRF11", asset_type="FII", quantity=10, price=9.8)


@pytest.mark.parametrize("args, error", [
    ({"ticker": "XX", "tipo": "FII", "quantidade": 1, "preco_medio": 1}, "Ticker inválido"),
    ({"ticker": "MXRF11", "tipo": "cripto", "quantidade": 1, "preco_medio": 1}, "Tipo deve ser"),
    ({"ticker": "MXRF11", "tipo": "FII", "quantidade": 0, "preco_medio": 1}, "Quantidade deve ser maior"),
    ({"ticker": "MXRF11", "tipo": "FII", "quantidade": "dez", "preco_medio": 1}, "devem ser números"),
])
def test_propose_asset_validation(propose, args, error):
    cards, run = propose
    assert error in run("propor_ativo", **args)["erro"]
    assert cards == []


def test_write_tools_need_a_card_list():
    execute = make_executor(make_settings(), NOW)
    assert "desconhecida" in execute("propor_evento", {"titulo": "X", "data": "2026-09-30"})["erro"]


# --- Chat devolve os cartões -------------------------------------------------------

class ProposingProvider:
    """Chama a ferramenta pedida e responde um texto fixo."""

    name = "falso"

    def __init__(self, tool, args):
        self.tool, self.args = tool, args

    def run(self, *, system, history, tools, execute, max_tool_rounds=2):
        self.result = execute(self.tool, self.args)
        return Reply(text="Preparei o cartão; confirme na tela.", model="falso", requests=2)


def test_chat_returns_event_card(client, monkeypatch):
    tomorrow = (datetime.now(TZ) + timedelta(days=1)).date().isoformat()
    fake = ProposingProvider("propor_evento", {"titulo": "Estudo", "data": tomorrow, "hora_inicio": "19:00"})
    monkeypatch.setattr(llm, "get_provider", lambda settings: fake)

    body = client.post("/api/chat", json={"message": "marque estudo amanhã às 19h"}).json()

    [card] = body["actions"]
    assert card["kind"] == "event"
    assert card["event"]["title"] == "Estudo"
    assert card["event"]["duration_minutes"] == 60


def test_chat_asset_card_reveals_nothing(client, monkeypatch):
    fake = ProposingProvider("propor_ativo", {"ticker": "MXRF11", "tipo": "FII", "quantidade": 1234, "preco_medio": 9.87})
    monkeypatch.setattr(llm, "get_provider", lambda settings: fake)

    res = client.post("/api/chat", json={"message": "adicione cotas"})

    assert res.json()["actions"][0]["ticker"] == "MXRF11"
    assert "1234" not in res.text and "9.87" not in res.text


# --- Confirmar evento ---------------------------------------------------------------

def propose_event(**kw):
    return actions.store.propose(datetime.now(TZ), event=event_draft(**kw))


def test_demo_mode_never_writes(client):
    proposal = propose_event()

    res = client.post(f"/api/actions/{proposal.id}/confirm").json()

    assert res["ok"] is True and "demonstração" in res["message"]
    assert not actions.HISTORY_FILE.exists()
    # Uma vez só
    again = client.post(f"/api/actions/{proposal.id}/confirm")
    assert again.status_code == 410


def test_cancel_then_confirm_fails(client):
    proposal = propose_event()

    assert client.post(f"/api/actions/{proposal.id}/cancel").json()["ok"] is True
    assert client.post(f"/api/actions/{proposal.id}/confirm").status_code == 410


def test_unknown_or_expired_card(client):
    assert client.post("/api/actions/inexistente/confirm").status_code == 410


def test_asset_cannot_be_confirmed_outside_private_tab(client):
    proposal = actions.store.propose(NOW, asset=AssetDraft(ticker="MXRF11", asset_type="FII", quantity=1, price=1))

    res = client.post(f"/api/actions/{proposal.id}/confirm")

    assert res.status_code == 400
    assert actions.store.get(proposal.id) is not None


def test_cross_site_confirm_is_blocked(client):
    proposal = propose_event()
    res = client.post(f"/api/actions/{proposal.id}/confirm", headers={"origin": "https://evil.example"})
    assert res.status_code == 403
    assert actions.store.get(proposal.id) is not None


class FakeAuth:
    def __init__(self, can_write=True):
        self.can_write = can_write
        self.rejected = False

    def credentials(self):
        return type("Creds", (), {"token": "access-simulado"})()

    def can_create_events(self):
        return self.can_write

    def mark_rejected(self):
        self.rejected = True


@pytest.fixture
def live_google(client, monkeypatch):
    """Modo real com o Google simulado. Devolve as requisições recebidas e a resposta a dar."""
    app.dependency_overrides[get_settings] = lambda: make_settings(demo_mode=False)
    auth = FakeAuth()
    monkeypatch.setattr(sources, "get_google_auth", lambda settings: auth)
    state = {"requests": [], "status": 200, "auth": auth}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        body = json.loads(request.content)
        return httpx.Response(state["status"], json={
            "id": "novo", "summary": body["summary"], "start": body["start"], "end": body["end"],
        })

    real = gcalendar.single_write_client
    monkeypatch.setattr(gcalendar, "single_write_client",
                        lambda method, url: real(method, url, transport=httpx.MockTransport(handler)))
    return state


def test_confirm_creates_event_in_primary_calendar(client, live_google):
    sources.get_cache().set(gcalendar.CACHE_KEY, [], 300)
    proposal = propose_event(title="Estudo de Cálculo")

    res = client.post(f"/api/actions/{proposal.id}/confirm").json()

    assert res["ok"] is True and "Evento criado" in res["message"]
    [request] = live_google["requests"]
    assert request.method == "POST"
    assert str(request.url) == "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    assert request.headers["authorization"] == "Bearer access-simulado"
    body = json.loads(request.content)
    assert body["summary"] == "Estudo de Cálculo"
    assert body["start"]["timeZone"] == "America/Sao_Paulo"
    assert "confirmação" in body["description"]
    # O painel da agenda busca de novo; a ação fica no histórico
    assert sources.get_cache().get_stale(gcalendar.CACHE_KEY) is None
    history = [json.loads(line) for line in actions.HISTORY_FILE.read_text(encoding="utf-8").splitlines()]
    assert history[0]["tipo"] == "evento" and "Estudo de Cálculo" in history[0]["resumo"]


def test_all_day_event_uses_dates(client, live_google):
    start = datetime.combine(datetime.now(TZ).date() + timedelta(days=2), datetime.min.time(), tzinfo=TZ)
    proposal = actions.store.propose(datetime.now(TZ), event=EventDraft(
        title="Feriado", start=start, end=start + timedelta(days=1), all_day=True))

    client.post(f"/api/actions/{proposal.id}/confirm")

    body = json.loads(live_google["requests"][0].content)
    assert body["start"] == {"date": start.date().isoformat()}
    assert body["end"] == {"date": (start.date() + timedelta(days=1)).isoformat()}


def test_old_read_only_connection_asks_to_reconnect(client, live_google):
    live_google["auth"].can_write = False
    proposal = propose_event()

    res = client.post(f"/api/actions/{proposal.id}/confirm").json()

    assert res["ok"] is False and res["action"] == "google_reconnect"
    assert "Gmail continua somente leitura" in res["message"]
    assert live_google["requests"] == []
    # Nada foi criado: o cartão continua valendo
    assert actions.store.get(proposal.id) is not None


def test_google_refusal_keeps_the_card(client, live_google):
    live_google["status"] = 403
    proposal = propose_event()

    res = client.post(f"/api/actions/{proposal.id}/confirm").json()

    assert res["ok"] is False and res["action"] == "google_reconnect"
    assert actions.store.get(proposal.id) is not None


def test_uncertain_failure_consumes_the_card(client, live_google):
    live_google["status"] = 503
    proposal = propose_event()

    res = client.post(f"/api/actions/{proposal.id}/confirm").json()

    assert res["ok"] is False
    assert "Confira na agenda" in res["message"]
    assert actions.store.get(proposal.id) is None
    assert not actions.HISTORY_FILE.exists()


def test_write_client_only_does_one_thing():
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    sent = []
    client = single_write_client("POST", url, transport=httpx.MockTransport(
        lambda r: sent.append(r) or httpx.Response(200, json={})))

    for method, target in [
        ("DELETE", url + "/abc"),  # apagar evento
        ("PUT", url + "/abc"),  # editar evento
        ("PATCH", url + "/abc"),
        ("GET", url),
        ("POST", "https://www.googleapis.com/calendar/v3/calendars/outra/events"),
        ("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"),
    ]:
        with pytest.raises(ConnectorError, match="Bloqueado"):
            client.request(method, target)
    assert sent == []
    client.post(url, json={})
    assert len(sent) == 1


def test_create_event_without_write_permission_sends_nothing(tmp_path):
    with pytest.raises(GoogleNotReady) as info:
        gcalendar.create_event(event_draft(), make_settings(), sources.get_cache(), FakeAuth(can_write=False))
    assert info.value.state == "needs_write"


# --- Confirmar ativo (aba privada) ---------------------------------------------------

@pytest.fixture
def private_client(client):
    app.dependency_overrides[get_settings] = lambda: make_settings(demo_mode=False, portfolio_access_key=KEY)
    assert client.post("/api/private/unlock", json={"key": KEY}).status_code == 200
    return client


def propose_asset(ticker="MXRF11", asset_type="FII", quantity=10, price=9.8):
    return actions.store.propose(datetime.now(TZ), asset=AssetDraft(
        ticker=ticker, asset_type=asset_type, quantity=quantity, price=price))


def test_private_actions_need_the_unlocked_tab(client):
    app.dependency_overrides[get_settings] = lambda: make_settings(demo_mode=False, portfolio_access_key=KEY)
    proposal = propose_asset()

    assert client.get("/api/private/actions").status_code == 401
    assert client.post(f"/api/private/actions/{proposal.id}/confirm").status_code == 401
    assert actions.store.get(proposal.id) is not None


def test_preview_shows_the_effect_on_the_portfolio(private_client):
    sources.PORTFOLIO_FILE.write_text("ticker,tipo,quantidade,preco_medio\nMXRF11,FII,10,10.20\n", encoding="utf-8")
    proposal = propose_asset()

    [preview] = private_client.get("/api/private/actions").json()

    assert preview["id"] == proposal.id
    assert preview["exists"] is True
    assert preview["current_quantity"] == 10 and preview["current_avg_price"] == 10.2
    assert preview["new_quantity"] == 20 and preview["new_avg_price"] == pytest.approx(10.0)


def test_confirm_asset_writes_backup_and_history(private_client):
    path = sources.PORTFOLIO_FILE
    path.write_text("ticker,tipo,quantidade,preco_medio\nMXRF11,FII,10,10.20\nPETR4,ação,5,30\n", encoding="utf-8")
    proposal = propose_asset()

    res = private_client.post(f"/api/private/actions/{proposal.id}/confirm").json()

    assert res["ok"] is True and "somado" in res["message"]
    assert path.read_text(encoding="utf-8") == "ticker,tipo,quantidade,preco_medio\nMXRF11,FII,20,10\nPETR4,ação,5,30\n"
    [backup] = (path.parent / "backups").iterdir()
    assert "MXRF11,FII,10,10.20" in backup.read_text(encoding="utf-8")
    assert json.loads(actions.HISTORY_FILE.read_text(encoding="utf-8"))["tipo"] == "ativo"
    # Uma vez só
    assert private_client.post(f"/api/private/actions/{proposal.id}/confirm").status_code == 410


def test_first_asset_creates_the_portfolio(private_client):
    proposal = propose_asset(ticker="VOO", asset_type="ETF Internacional", quantity=0.5, price=540)

    assert private_client.post(f"/api/private/actions/{proposal.id}/confirm").json()["ok"] is True

    assert sources.PORTFOLIO_FILE.read_text(encoding="utf-8") == \
        "ticker,tipo,quantidade,preco_medio\nVOO,ETF Internacional,0.5,540\n"


def test_type_conflict_is_explained_and_keeps_the_card(private_client):
    sources.PORTFOLIO_FILE.write_text("ticker,tipo,quantidade,preco_medio\nBOVA11,ETF,1,100\n", encoding="utf-8")
    proposal = propose_asset(ticker="BOVA11", asset_type="FII")

    [preview] = private_client.get("/api/private/actions").json()
    assert "já está na carteira como ETF" in preview["problem"]

    res = private_client.post(f"/api/private/actions/{proposal.id}/confirm").json()
    assert res["ok"] is False
    assert actions.store.get(proposal.id) is not None
    assert "BOVA11,ETF,1,100" in sources.PORTFOLIO_FILE.read_text(encoding="utf-8")
