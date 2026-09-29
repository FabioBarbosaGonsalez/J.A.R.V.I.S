"""Dólar comercial ao vivo pela AwesomeAPI (gratuita, sem chave).

    GET https://economia.awesomeapi.com.br/json/last/USD-BRL

O câmbio da brapi só existe nos planos pagos. Sem chave, a AwesomeAPI guarda
cada cotação por até 1 minuto, o que basta para um painel "ao vivo".
Os números vêm como texto.
"""

from datetime import datetime, timezone

import httpx

from app.connectors.http import ConnectorError, get
from app.models import FxQuote

FX_URL = "https://economia.awesomeapi.com.br/json/last/USD-BRL"


def fetch_usd_brl(http: httpx.Client) -> FxQuote:
    response = get(http, FX_URL, what="a cotação do dólar")
    try:
        data = response.json()["USDBRL"]
        return FxQuote(
            pair="USD-BRL",
            bid=float(data["bid"]),
            pct_change=float(data["pctChange"]),
            high=float(data["high"]),
            low=float(data["low"]),
            updated_at=datetime.fromtimestamp(int(data["timestamp"]), timezone.utc),
        )
    except (ValueError, KeyError, TypeError):
        raise ConnectorError("Resposta inesperada da cotação do dólar.") from None
