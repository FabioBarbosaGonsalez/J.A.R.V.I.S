"""Cliente da brapi v2 com a API simulada (nenhuma chamada real)."""

import httpx
import pytest

from app.connectors import brapi
from app.connectors.http import ConnectorError, read_only_client

TOKEN = "brapi-token-secreto"


def quote_body(symbol, price=10.5, change=1.2, currency="BRL"):
    return {
        "results": [{
            "requestedSymbol": symbol, "symbol": symbol, "changed": False,
            "data": {"shortName": f"{symbol} SA", "currency": currency, "regularMarketPrice": price,
                     "regularMarketChangePercent": change, "regularMarketTime": "2026-09-29T20:43:30.000Z"},
        }],
        "requestedAt": "2026-09-29T20:43:35.000Z", "took": 12,
    }


def client(handler):
    return read_only_client(transport=httpx.MockTransport(handler))


def test_fetch_quote_returns_results_data():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=quote_body("B3SA3"),
                              headers={"x-ratelimit-remaining": "14990", "x-ratelimit-limit": "15000"})

    quote = brapi.fetch_quote(client(handler), TOKEN, "B3SA3")

    assert (quote.price, quote.change_pct, quote.currency, quote.short_name) == (10.5, 1.2, "BRL", "B3SA3 SA")
    assert quote.market_time.year == 2026
    request = seen[0]
    assert str(request.url) == "https://brapi.dev/api/v2/stocks/quote?symbols=B3SA3"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(request.url)


def test_reads_quota_headers():
    def handler(request):
        return httpx.Response(200, json=quote_body("VOO", currency="USD"),
                              headers={"x-ratelimit-remaining": "120", "x-ratelimit-limit": "15000"})

    batch = brapi.fetch_quotes(client(handler), TOKEN, ["VOO"])
    assert batch.quota == brapi.Quota(remaining=120, limit=15000)
    assert batch.quotes["VOO"].currency == "USD"


@pytest.mark.parametrize("status, body, expected", [
    (401, {"error": True, "message": "Token inválido"}, "Confira BRAPI_TOKEN"),
    (400, {"error": True, "message": "Seu plano permite no máximo 1 ativo(s) por requisição."}, "no máximo 1 ativo"),
    (429, {"error": True}, "Limite de requisições"),
    (503, {"error": True}, "instável"),
])
def test_non_2xx_becomes_readable_error(status, body, expected):
    with pytest.raises(ConnectorError, match=expected) as info:
        brapi.fetch_quote(client(lambda r: httpx.Response(status, json=body)), TOKEN, "B3SA3")
    assert info.value.status == status
    assert TOKEN not in str(info.value)


def test_missing_data_is_404():
    empty = {"results": [], "requestedAt": "x", "took": 1}
    with pytest.raises(ConnectorError) as info:
        brapi.fetch_quote(client(lambda r: httpx.Response(200, json=empty)), TOKEN, "XPTO3")
    assert info.value.status == 404


def test_unexpected_body():
    with pytest.raises(ConnectorError, match="inesperada"):
        brapi.fetch_quote(client(lambda r: httpx.Response(200, text="<html>")), TOKEN, "B3SA3")
