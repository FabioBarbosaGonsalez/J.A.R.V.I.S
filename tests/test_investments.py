"""Carteira e mercado: CSV, cotações da brapi v2 e dólar, com as APIs simuladas."""

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.cache import Cache
from app.connectors import investments
from app.connectors.http import read_only_client
from app.connectors.investments import PortfolioFileError, quote_ttl, read_portfolio
from tests.conftest import make_settings

TOKEN = "brapi-token-secreto"
PRICES = {  # ticker: (preço, variação %, moeda)
    "PETR4": (36.8, 0.9, "BRL"),
    "MXRF11": (9.78, 0.1, "BRL"),
    "VOO": (700.0, -0.2, "USD"),
}
USD_BRL = 5.0
HEADER = "ticker,tipo,quantidade,preco_medio\n"


def write(tmp_path, text: str, encoding="utf-8"):
    path = tmp_path / "carteira.csv"
    path.write_bytes(text.encode(encoding))
    return path


# --- CSV ---------------------------------------------------------------------

def test_reads_standard_csv(tmp_path):
    path = write(tmp_path, HEADER + "PETR4,ação,100,32.50\nmxrf11,FII,300,10.15\n")
    holdings = read_portfolio(path)
    assert [(h.ticker, h.asset_type, h.quantity, h.avg_price) for h in holdings] == [
        ("PETR4", "ação", 100, 32.5),
        ("MXRF11", "FII", 300, 10.15),
    ]


def test_international_etf_with_fractional_quantity(tmp_path):
    path = write(tmp_path, HEADER + "VOO,ETF Internacional,0.75,540.00\nagg,etf internacional,0.5,95.00\n")
    voo, agg = read_portfolio(path)
    assert (voo.ticker, voo.asset_type, voo.quantity) == ("VOO", "ETF Internacional", 0.75)
    assert agg.ticker == "AGG"  # 3 letras: ticker americano válido


def test_treasury_bonds_keep_their_name(tmp_path):
    path = write(tmp_path, HEADER + "Tesouro  Selic 2031,Tesouro Direto,0.20,15000.00\n")
    [bond] = read_portfolio(path)
    assert (bond.ticker, bond.asset_type, bond.quantity, bond.quoted) == ("Tesouro Selic 2031", "Tesouro Direto", 0.20, False)


def test_reads_excel_ptbr_csv(tmp_path):
    text = "﻿Ticker;Tipo;Quantidade;Preço Médio\nBOVA11;etf;1.000;1.234,56\n\n"
    [h] = read_portfolio(write(tmp_path, text))
    assert (h.ticker, h.asset_type, h.quantity, h.avg_price) == ("BOVA11", "ETF", 1000, 1234.56)


@pytest.mark.parametrize("sep, raw, expected", [
    (";", "1.000", 1000),  # Excel pt-BR: ponto separa milhares
    (";", "32.50", 32.5),  # mas "32.50" digitado à mão continua decimal
    (";", "0,632", 0.632),  # fracionado com vírgula
    (",", "0.632", 0.632),
    (",", '"1.234,56"', 1234.56),
])
def test_number_formats(tmp_path, sep, raw, expected):
    header = sep.join(["ticker", "tipo", "quantidade", "preco_medio"])
    path = write(tmp_path, f"{header}\nPETR4{sep}ação{sep}{raw}{sep}{raw}\n")
    [h] = read_portfolio(path)
    assert h.quantity == h.avg_price == expected


def test_reads_windows_ansi_csv(tmp_path):
    path = write(tmp_path, "ticker;tipo;quantidade;preco_medio\nPETR4;ação;10;30,00\n", encoding="cp1252")
    assert read_portfolio(path)[0].asset_type == "ação"


def test_merges_duplicate_tickers(tmp_path):
    path = write(tmp_path, HEADER + "PETR4,acao,100,30\nPETR4,acao,100,40\n")
    [h] = read_portfolio(path)
    assert (h.quantity, h.avg_price) == (200, 35)


@pytest.mark.parametrize("line, expected", [
    ("PETR-4,ação,10,30", "Linha 2: ticker inválido"),
    ("VOO1,ETF Internacional,1,30", "Linha 2: ticker inválido"),
    ("PETR4,cripto,10,30", "Linha 2: tipo deve ser"),
    ("PETR4,ação,dez,30", "Linha 2: quantidade inválido"),
    ("PETR4,ação,0,30", "Linha 2: quantidade deve ser maior que zero"),
])
def test_invalid_lines_point_to_the_problem(tmp_path, line, expected):
    with pytest.raises(PortfolioFileError, match=expected):
        read_portfolio(write(tmp_path, HEADER + line + "\n"))


def test_missing_columns(tmp_path):
    with pytest.raises(PortfolioFileError, match="preco_medio"):
        read_portfolio(write(tmp_path, "ticker,tipo,quantidade\nPETR4,ação,10\n"))


# --- Horário de pregão ---------------------------------------------------------

SP = ZoneInfo("America/Sao_Paulo")


@pytest.mark.parametrize("when, currency, expected_hours", [
    (datetime(2026, 9, 29, 14, 0, tzinfo=SP), "BRL", 0.5),  # terça, pregão aberto
    (datetime(2026, 9, 29, 20, 0, tzinfo=SP), "BRL", 14),  # terça à noite: até quarta 10h
    (datetime(2026, 10, 3, 12, 0, tzinfo=SP), "BRL", 46),  # sábado: até segunda 10h
    (datetime(2026, 9, 29, 12, 0, tzinfo=SP), "USD", 0.5),  # 11h em Nova York: aberto
    (datetime(2026, 9, 29, 9, 0, tzinfo=SP), "USD", 1.5),  # 8h em Nova York: abre 9h30
])
def test_quote_ttl_follows_market_hours(when, currency, expected_hours):
    assert quote_ttl(currency, when) == pytest.approx(expected_hours * 3600)


# --- brapi + dólar ---------------------------------------------------------------

class FakeApis:
    """Simula a brapi v2 e a AwesomeAPI. `fail` mapeia ticker -> código HTTP."""

    def __init__(self, fail=None, remaining=14000, fx_status=200):
        self.fail = fail or {}
        self.remaining = remaining
        self.fx_status = fx_status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "economia.awesomeapi.com.br":
            if self.fx_status != 200:
                return httpx.Response(self.fx_status)
            return httpx.Response(200, json={"USDBRL": {
                "bid": str(USD_BRL), "pctChange": "-0.3", "high": "5.1", "low": "4.9", "timestamp": "1790714191"}})
        symbols = request.url.params["symbols"].split(",")
        for s in symbols:
            if s in self.fail:
                return httpx.Response(self.fail[s], json={"error": True, "message": "erro simulado"})
        results = [{
            "requestedSymbol": s, "symbol": s, "changed": False,
            "data": {"shortName": s, "currency": PRICES[s][2], "regularMarketPrice": PRICES[s][0],
                     "regularMarketChangePercent": PRICES[s][1], "regularMarketTime": "2026-09-29T20:00:00.000Z"},
        } for s in symbols]
        return httpx.Response(200, json={"results": results, "requestedAt": "x", "took": 1}, headers={
            "x-ratelimit-remaining": str(self.remaining), "x-ratelimit-limit": "15000"})

    def quote_requests(self):
        return [r for r in self.requests if r.url.host == "brapi.dev"]


@pytest.fixture
def cache(tmp_path):
    return Cache(tmp_path / "cache.sqlite3")


@pytest.fixture
def portfolio_file(tmp_path):
    return write(tmp_path, HEADER + "PETR4,ação,100,32.50\nMXRF11,FII,300,10.15\n"
                 "VOO,ETF Internacional,0.5,600\nTesouro Selic 2031,Tesouro Direto,0.20,15000.00\n")


def run(load, fake, cache, portfolio_file, **settings):
    settings.setdefault("brapi_token", TOKEN)
    s = make_settings(demo_mode=False, **settings)
    return load(s, cache, read_only_client(transport=httpx.MockTransport(fake)), portfolio_file)


def market(*args, **kwargs):
    return run(investments.load_market, *args, **kwargs)


def portfolio(*args, **kwargs):
    return run(investments.load_portfolio, *args, **kwargs)


def test_not_configured_without_file_or_token(cache, tmp_path, portfolio_file):
    assert market(FakeApis(), cache, tmp_path / "nao-existe.csv").status == "not_configured"
    res = market(FakeApis(), cache, portfolio_file, brapi_token=None)
    assert res.status == "not_configured" and "BRAPI_TOKEN" in res.message


def test_market_shows_dollar_and_quotes_without_amounts(cache, portfolio_file):
    fake = FakeApis()
    res = market(fake, cache, portfolio_file)

    assert res.status == "ok" and res.message is None
    assert res.data.usd_brl.bid == USD_BRL
    by_ticker = {q.ticker: q for q in res.data.quotes}
    assert (by_ticker["PETR4"].price, by_ticker["PETR4"].currency) == (36.8, "BRL")
    assert (by_ticker["VOO"].price, by_ticker["VOO"].currency) == (700.0, "USD")  # só em US$, sem conversão
    assert by_ticker["Tesouro Selic 2031"].price is None and "Sem cotação" in by_ticker["Tesouro Selic 2031"].note
    # Nada de quantidade ou valor investido na resposta da home
    body = res.model_dump_json()
    assert "quantity" not in body and "avg_price" not in body and "market_value" not in body


def test_free_plan_one_ticker_per_request_on_v2(cache, portfolio_file):
    fake = FakeApis()
    market(fake, cache, portfolio_file)
    urls = [str(r.url) for r in fake.quote_requests()]
    assert urls == [f"https://brapi.dev/api/v2/stocks/quote?symbols={t}" for t in ("PETR4", "MXRF11", "VOO")]
    assert all(r.headers["Authorization"] == f"Bearer {TOKEN}" for r in fake.quote_requests())


def test_paid_plan_groups_tickers(cache, portfolio_file):
    fake = FakeApis()
    market(fake, cache, portfolio_file, brapi_tickers_per_request=10)
    assert [r.url.params["symbols"] for r in fake.quote_requests()] == ["PETR4,MXRF11,VOO"]


def test_market_and_portfolio_share_the_cache(cache, portfolio_file):
    fake = FakeApis()
    market(fake, cache, portfolio_file)
    portfolio(fake, cache, portfolio_file)
    market(fake, cache, portfolio_file)
    assert len(fake.quote_requests()) == 3  # só as da primeira vez
    assert sum(r.url.host == "economia.awesomeapi.com.br" for r in fake.requests) == 1  # dólar: 1 minuto


def test_portfolio_converts_dollar_assets(cache, portfolio_file):
    res = portfolio(FakeApis(), cache, portfolio_file)
    voo = next(p for p in res.data.positions if p.ticker == "VOO")
    assert (voo.currency, voo.fx, voo.market_value, voo.cost) == ("USD", USD_BRL, 1750.0, 1500.0)
    assert voo.result_pct == pytest.approx(16.67)  # medido em dólar, sem efeito do câmbio
    assert "Tesouro Selic 2031" in res.message  # fora dos totais, sem cotação


def test_unknown_ticker_does_not_hide_the_rest(cache, portfolio_file):
    res = market(FakeApis(fail={"MXRF11": 404}), cache, portfolio_file)
    by_ticker = {q.ticker: q for q in res.data.quotes}
    assert by_ticker["PETR4"].price == 36.8
    assert by_ticker["MXRF11"].note == "Ticker não reconhecido."
    assert res.message == "A brapi não reconheceu: MXRF11."


def test_rate_limit_stops_fetching(cache, portfolio_file):
    fake = FakeApis(fail={"MXRF11": 429})
    res = market(fake, cache, portfolio_file)
    assert "Limite de requisições" in res.message
    assert [r.url.params["symbols"] for r in fake.quote_requests()] == ["PETR4", "MXRF11"]  # parou no erro
    assert {q.ticker: q.note for q in res.data.quotes}["VOO"] == "Ainda sem cotação."


def test_falls_back_to_stale_quotes(cache, portfolio_file):
    market(FakeApis(), cache, portfolio_file)
    for t in ("PETR4", "MXRF11", "VOO"):  # vence o cache
        key = f"brapi:quote:{t}"
        cache.set(key, cache.get_stale(key).value, ttl_seconds=-1)

    res = market(FakeApis(fail={"PETR4": 503}), cache, portfolio_file)
    assert res.status == "ok"
    assert all(q.price for q in res.data.quotes if q.asset_type != "Tesouro Direto")
    assert "instável" in res.message and "Mostrando cotações de" in res.message


def test_pauses_as_soon_as_brapi_reports_low_quota(cache, portfolio_file):
    fake = FakeApis(remaining=500)  # 500 de 15000: menos de 5%
    res = market(fake, cache, portfolio_file)
    assert [r.url.params["symbols"] for r in fake.quote_requests()] == ["PETR4"]  # parou depois da 1ª
    assert "Cota da brapi quase no fim" in res.message
    assert {q.ticker: q.price for q in res.data.quotes}["PETR4"] == 36.8


def test_stays_paused_with_stale_quotes(cache, portfolio_file):
    market(FakeApis(), cache, portfolio_file)
    cache.set(investments.QUOTA_KEY, {"remaining": 100, "limit": 15000}, ttl_seconds=3600)
    for t in ("PETR4", "MXRF11", "VOO"):  # vence o cache
        key = f"brapi:quote:{t}"
        cache.set(key, cache.get_stale(key).value, ttl_seconds=-1)

    fake = FakeApis()
    res = market(fake, cache, portfolio_file)
    assert fake.quote_requests() == []
    assert "Mostrando cotações de" in res.message
    assert all(q.price for q in res.data.quotes if q.asset_type != "Tesouro Direto")


def test_dollar_failure_uses_last_known_rate(cache, portfolio_file):
    market(FakeApis(), cache, portfolio_file)
    cache.set("fx:usd-brl", cache.get_stale("fx:usd-brl").value, ttl_seconds=-1)
    res = market(FakeApis(fx_status=503), cache, portfolio_file)
    assert res.data.usd_brl.bid == USD_BRL
    assert "Usando o dólar de" in res.message


def test_no_dollar_at_all_keeps_quotes(cache, portfolio_file):
    res = market(FakeApis(fx_status=503), cache, portfolio_file)
    assert res.status == "ok" and res.data.usd_brl is None
    assert {q.ticker: q.price for q in res.data.quotes}["VOO"] == 700.0
    assert "sem conversão" in res.message


def test_error_when_token_is_rejected_and_nothing_cached(cache, portfolio_file):
    res = portfolio(FakeApis(fail={"PETR4": 401}), cache, portfolio_file)
    assert res.status == "error" and "BRAPI_TOKEN" in res.message
    assert TOKEN not in res.message
