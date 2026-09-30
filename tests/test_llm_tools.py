"""Ferramentas da IA: filtros, datas e o que nunca pode ir para o modelo."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import sources
from app.llm.tools import TOOLS, make_executor
from app.models import (
    AssetQuote,
    CalendarEvent,
    Deliverable,
    Dividend,
    Email,
    FxQuote,
    Market,
    PanelResponse,
    Portfolio,
    Position,
)
from tests.conftest import make_settings

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=TZ)  # terça-feira


def at(days: int, hour: int = 0, minute: int = 0) -> datetime:
    return (NOW + timedelta(days=days)).replace(hour=hour, minute=minute)


def ok(data) -> PanelResponse:
    return PanelResponse(status="ok", source="live", updated_at=NOW, data=data)


@pytest.fixture
def settings():
    return make_settings(demo_mode=False)


@pytest.fixture
def run(settings):
    execute = make_executor(settings, NOW)
    return lambda name, **args: execute(name, args)


@pytest.fixture
def panels(monkeypatch):
    """Troca o painel de cada fonte por dados fixos."""

    def set_panel(name: str, panel: PanelResponse):
        monkeypatch.setattr(sources, name, lambda settings, **kw: panel)

    return set_panel


# --- Agenda -----------------------------------------------------------------

EVENTS = [
    CalendarEvent(id="1", title="Feriado de ontem", start=at(-1), end=at(0), all_day=True),
    CalendarEvent(id="2", title="Reunião", start=at(0, 14), end=at(0, 15), location="Sala 3"),
    CalendarEvent(id="3", title="Estudo de Cálculo", start=at(1, 19), end=at(1, 21)),
    CalendarEvent(id="4", title="Congresso", start=at(2), end=at(4), all_day=True),
]


def test_events_default_to_today(run, panels):
    panels("calendar_panel", ok(EVENTS))

    result = run("listar_eventos")["resultado"]

    assert result["periodo"] == "2026-09-29 (terça) a 2026-09-29 (terça)"
    # O dia inteiro de ontem termina hoje à 00:00 e não conta como de hoje
    assert result["eventos"] == [{
        "titulo": "Reunião", "inicio": "2026-09-29 (terça) 14:00",
        "fim": "2026-09-29 (terça) 15:00", "local": "Sala 3",
    }]
    assert "aviso" not in result


def test_events_in_a_range(run, panels):
    panels("calendar_panel", ok(EVENTS))

    result = run("listar_eventos", data_inicial="2026-09-30", data_final="2026-10-02")["resultado"]

    assert [e["titulo"] for e in result["eventos"]] == ["Estudo de Cálculo", "Congresso"]
    congress = result["eventos"][1]
    assert congress == {
        "titulo": "Congresso", "inicio": "2026-10-01 (quinta)",
        "fim": "2026-10-02 (sexta)", "dia_inteiro": True,
    }


def test_multi_day_event_shows_on_a_middle_day(run, panels):
    panels("calendar_panel", ok(EVENTS))

    result = run("listar_eventos", data_inicial="2026-10-02")["resultado"]

    assert [e["titulo"] for e in result["eventos"]] == ["Congresso"]


def test_events_outside_window_warn(run, panels):
    panels("calendar_panel", ok(EVENTS))

    result = run("listar_eventos", data_inicial="2026-10-20")["resultado"]

    assert result["eventos"] == []
    assert "2026-10-06" in result["aviso"]


def test_reversed_dates_are_swapped(run, panels):
    panels("calendar_panel", ok(EVENTS))

    result = run("listar_eventos", data_inicial="2026-09-30", data_final="2026-09-29")["resultado"]

    assert [e["titulo"] for e in result["eventos"]] == ["Reunião", "Estudo de Cálculo"]


def test_bad_date_goes_back_to_the_model(run, panels):
    panels("calendar_panel", ok(EVENTS))

    assert "AAAA-MM-DD" in run("listar_eventos", data_inicial="amanhã")["erro"]


def test_unavailable_source(run, panels):
    panels("calendar_panel", PanelResponse(status="not_configured", updated_at=NOW, message="Conecte o Google"))

    assert run("listar_eventos") == {"indisponivel": "não configurado"}


# --- E-mails ----------------------------------------------------------------

EMAILS = [
    Email(id="1", sender_name="Prof. Ana", sender_email="ana@puc-campinas.edu.br", subject="Prova de Cálculo",
          snippet="Conteúdo confidencial da mensagem", received_at=at(0, 8), unread=True, from_university=True),
    Email(id="2", sender_name="Loja", sender_email="ofertas@loja.com", subject="Promoção",
          snippet="Compre já", received_at=at(-1, 9), unread=True),
    Email(id="3", sender_name="Banco", sender_email="banco@banco.com", subject="Extrato",
          snippet="Seu saldo é", received_at=at(-2, 9), unread=False),
]


def test_emails_never_send_body_or_address(run, panels):
    panels("emails_panel", ok(EMAILS))

    result = run("listar_emails")
    text = str(result)

    assert "confidencial" not in text and "Seu saldo" not in text
    assert "@" not in text
    first = result["resultado"]["emails"][0]
    assert first == {
        "de": "Prof. Ana", "assunto": "Prova de Cálculo",
        "recebido": "2026-09-29 (terça) 08:00", "lido": False, "faculdade": True,
    }


def test_email_filters_and_limit(run, panels):
    panels("emails_panel", ok(EMAILS))

    unread = run("listar_emails", apenas_nao_lidos=True)["resultado"]
    assert [e["de"] for e in unread["emails"]] == ["Prof. Ana", "Loja"]
    assert unread["nao_lidos_na_caixa"] == 2

    uni = run("listar_emails", apenas_faculdade=True)["resultado"]
    assert [e["de"] for e in uni["emails"]] == ["Prof. Ana"]

    limited = run("listar_emails", limite=1)["resultado"]
    assert len(limited["emails"]) == 1
    assert limited["total_encontrado"] == 3

    # Limite absurdo vira o máximo permitido; texto vira erro para o modelo
    assert len(run("listar_emails", limite=999)["resultado"]["emails"]) == 3
    assert "erro" in run("listar_emails", limite="muitos")


# --- Faculdade --------------------------------------------------------------

def deliverable(id_, title, hours, status="pending"):
    return Deliverable(id=id_, title=title, course="Cálculo", due_at=datetime.now(TZ) + timedelta(hours=hours),
                       status=status, url="https://canvas/segredo")


def test_deliverables_sorted_without_links(run, panels):
    panels("canvas_panel", ok([
        deliverable("1", "Lista 3", 100),
        deliverable("2", "Lista 2", 20.5),
        deliverable("3", "Lista 1", 5, status="submitted"),
        deliverable("4", "Lista 0", -3),
    ]))

    result = run("listar_entregas")
    items = result["resultado"]["entregas"]

    assert [d["titulo"] for d in items] == ["Lista 2", "Lista 3"]
    assert items[0]["urgente"] is True
    assert items[0]["faltam"] == "20 horas"
    assert items[0]["situacao"] == "pendente"
    assert "canvas" not in str(result)

    with_done = run("listar_entregas", incluir_entregues=True)["resultado"]["entregas"]
    assert [d["titulo"] for d in with_done] == ["Lista 1", "Lista 2", "Lista 3"]


# --- Carteira ---------------------------------------------------------------

def test_portfolio_only_percentages(run, panels):
    panels("market_panel", ok(Market(
        usd_brl=FxQuote(pair="USD-BRL", bid=5.4321, pct_change=-0.3, high=5.5, low=5.4, updated_at=NOW),
        quotes=[
            AssetQuote(ticker="MXRF11", asset_type="FII", currency="BRL", price=9.87, change_pct=0.5),
            AssetQuote(ticker="IVVB11", asset_type="ETF", note="sem cotação agora"),
        ],
    )))
    panels("portfolio_panel", ok(Portfolio(
        positions=[Position(ticker="MXRF11", asset_type="FII", quantity=1234, avg_price=9.5,
                            price=9.87, day_change_pct=0.5)],
        dividends=[Dividend(ticker="MXRF11", kind="Rendimento", value_per_share=0.09,
                            payment_date=NOW.date() + timedelta(days=5), estimated_total=111.06)],
    )))

    result = run("resumo_carteira")
    data = result["resultado"]

    assert data["dolar"] == {"cotacao_reais": 5.4321, "variacao_dia_pct": -0.3}
    assert data["ativos"][1] == {"ticker": "IVVB11", "tipo": "ETF", "sem_cotacao": "sem cotação agora"}
    assert data["carteira"]["resultado_sobre_preco_medio_pct"] == 3.89
    assert data["carteira"]["alocacao_pct"] == {"FII": 100.0}
    assert data["proximos_proventos"][0]["valor_por_cota"] == 0.09
    # Nada de quantidade, valor investido, patrimônio ou total de proventos
    text = str(result)
    for secret in ("1234", "12179", "11723", "111.06", "quantidade", "valor_total"):
        assert secret not in text


def test_portfolio_unavailable(run, panels):
    down = PanelResponse(status="error", updated_at=NOW, message="brapi fora do ar")
    panels("market_panel", down)
    panels("portfolio_panel", down)

    assert "indisponivel" in run("resumo_carteira")


# --- Geral ------------------------------------------------------------------

def test_unknown_tool(run):
    assert "desconhecida" in run("apagar_tudo")["erro"]


def test_tools_have_valid_schemas():
    for tool in TOOLS:
        assert tool.parameters["type"] == "object"
        assert tool.description


def test_demo_mode_answers_every_tool():
    execute = make_executor(make_settings(demo_mode=True), datetime.now(TZ))
    for tool in TOOLS:
        assert "resultado" in execute(tool.name, {}), tool.name
