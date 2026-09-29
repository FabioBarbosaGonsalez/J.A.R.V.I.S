"""Cliente tipado da brapi v2: cotações da B3 e de ativos dos EUA.

    GET https://brapi.dev/api/v2/stocks/quote?symbols=B3SA3
    Authorization: Bearer <BRAPI_TOKEN>

O token vem do .env (via `app.config`) e só existe no servidor: nunca vai para
o navegador, para a URL nem para as mensagens de erro.

A resposta traz um item por ticker em `results`, com os dados em
`results[].data`. A brapi também informa a cota restante no header
`x-ratelimit-remaining` (janela móvel de 30 dias), que usamos para não
estourar o plano gratuito.
"""

from dataclasses import dataclass
from datetime import datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.connectors.http import ConnectorError, get

QUOTE_URL = "https://brapi.dev/api/v2/stocks/quote"

ERRORS = {401: "A brapi recusou o token. Confira BRAPI_TOKEN no .env."}


class BrapiQuote(BaseModel):
    """`results[].data` da cotação (só os campos que o painel usa)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    short_name: str | None = Field(default=None, alias="shortName")
    currency: str = "BRL"
    price: float = Field(alias="regularMarketPrice")
    change_pct: float = Field(default=0.0, alias="regularMarketChangePercent")
    market_time: datetime | None = Field(default=None, alias="regularMarketTime")


@dataclass
class Quota:
    remaining: int
    limit: int


@dataclass
class QuoteBatch:
    quotes: dict[str, BrapiQuote]  # pelo ticker pedido
    quota: Quota | None


def fetch_quotes(http: httpx.Client, token: str, symbols: list[str]) -> QuoteBatch:
    """Cotações de um ou mais tickers (o plano gratuito aceita um por chamada).

    Levanta `ConnectorError` em respostas não-2xx; `status == 404` quando a
    brapi não encontra o ticker.
    """
    response = get(
        http, QUOTE_URL, what="a brapi", status_messages=ERRORS, use_body_message=True,
        params={"symbols": ",".join(symbols)},
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        results = response.json()["results"]
    except (ValueError, KeyError, TypeError):
        raise ConnectorError("Resposta inesperada da brapi.") from None

    quotes: dict[str, BrapiQuote] = {}
    for item in results:
        try:
            requested = str(item.get("requestedSymbol") or item["symbol"]).upper()
            quotes[requested] = BrapiQuote.model_validate(item["data"])
        except (KeyError, TypeError, AttributeError, ValidationError):
            continue  # item sem preço: tratado como "sem cotação"
    return QuoteBatch(quotes=quotes, quota=_quota(response))


def fetch_quote(http: httpx.Client, token: str, symbol: str) -> BrapiQuote:
    """Cotação de um ticker: devolve `results[0].data`."""
    batch = fetch_quotes(http, token, [symbol])
    try:
        return batch.quotes[symbol.upper()]
    except KeyError:
        raise ConnectorError(f"A brapi não trouxe cotação para {symbol}.", status=404) from None


def _quota(response: httpx.Response) -> Quota | None:
    try:
        return Quota(
            remaining=int(response.headers["x-ratelimit-remaining"]),
            limit=int(response.headers["x-ratelimit-limit"]),
        )
    except (KeyError, ValueError):
        return None
