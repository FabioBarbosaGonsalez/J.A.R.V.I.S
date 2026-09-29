import httpx
import pytest

from app.connectors.fx import fetch_usd_brl
from app.connectors.http import ConnectorError, read_only_client

BODY = {"USDBRL": {"code": "USD", "codein": "BRL", "high": "5.2411", "low": "5.1976", "varBid": "-0.0158",
                   "pctChange": "-0.302509", "bid": "5.2072", "ask": "5.2084", "timestamp": "1790714191"}}


def client(handler):
    return read_only_client(transport=httpx.MockTransport(handler))


def test_parses_awesomeapi():
    fx = fetch_usd_brl(client(lambda r: httpx.Response(200, json=BODY)))
    assert (fx.bid, round(fx.pct_change, 2), fx.high, fx.low) == (5.2072, -0.3, 5.2411, 5.1976)
    assert fx.updated_at.year == 2026


@pytest.mark.parametrize("response", [
    httpx.Response(200, json={"outro": {}}),
    httpx.Response(200, json={"USDBRL": {"bid": "abc"}}),
    httpx.Response(503),
])
def test_errors(response):
    with pytest.raises(ConnectorError):
        fetch_usd_brl(client(lambda r: response))
