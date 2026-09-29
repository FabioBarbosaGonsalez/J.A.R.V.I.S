"""Carteira: posições do `data/carteira.csv`, cotações da brapi e dólar da AwesomeAPI.

Sem scraping e sem login em corretora: as posições são suas, num CSV local.

Dois painéis saem daqui:
- `load_market`: o que a home mostra. Dólar ao vivo e a cotação de cada ativo,
  sem quantidade nem valor investido.
- `load_portfolio`: a carteira completa em reais (para o briefing e, na Fase 4,
  para a IA). Ativos em dólar são convertidos pela cotação do momento.

Limites do plano gratuito da brapi (brapi.dev/pricing): 1 ativo por
requisição, 15 mil requisições em 30 dias e dados atualizados a cada 30 minutos.
Por isso:
- cada cotação fica 30 minutos no cache durante o pregão; fora dele, até a
  próxima abertura (a cotação não muda com o mercado fechado);
- só buscamos os ativos cujo cache venceu, um por vez;
- a brapi informa a cota restante em cada resposta; com menos de 5% sobrando,
  as buscas param e o painel segue com as últimas cotações conhecidas.
"""

import csv
import io
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from app.cache import Cache, Entry
from app.config import Settings, secret
from app.connectors import brapi
from app.connectors.fx import fetch_usd_brl
from app.connectors.http import ConnectorError
from app.formatting import normalize
from app.models import (
    AssetQuote, AssetType, FxQuote, Market, PanelResponse, Portfolio, Position, UnquotedPosition,
)

QUOTE_TTL = 30 * 60
FX_TTL = 60
QUOTA_RESERVE = 0.05  # para as buscas com menos de 5% da cota sobrando
QUOTA_KEY = "brapi:quota"
FX_KEY = "fx:usd-brl"

# Pregão de cada moeda: (fuso, abertura, fechamento)
MARKET_HOURS = {
    "BRL": (ZoneInfo("America/Sao_Paulo"), dtime(10, 0), dtime(18, 30)),
    "USD": (ZoneInfo("America/New_York"), dtime(9, 30), dtime(16, 15)),
}

B3_TICKER_RE = re.compile(r"^[A-Z0-9]{4,7}$")
US_TICKER_RE = re.compile(r"^[A-Z]{1,5}([.-][A-Z])?$")
ASSET_TYPES: dict[str, AssetType] = {
    "acao": "ação", "acoes": "ação", "fii": "FII", "fiis": "FII",
    "etf": "ETF", "etfs": "ETF", "bdr": "BDR", "bdrs": "BDR",
    "etf internacional": "ETF Internacional", "etf exterior": "ETF Internacional",
    "tesouro direto": "Tesouro Direto", "tesouro": "Tesouro Direto",
}
# Sem cotação ao vivo gratuita (os títulos do Tesouro só existem nos planos pagos da brapi)
NO_LIVE_QUOTE: set[AssetType] = {"Tesouro Direto"}
COLUMNS = {"ticker", "tipo", "quantidade", "preco_medio"}

_lock = threading.Lock()


class PortfolioFileError(Exception):
    """Problema no carteira.csv. A mensagem diz a linha e o que corrigir."""


@dataclass
class Holding:
    ticker: str
    asset_type: AssetType
    quantity: float
    avg_price: float  # na moeda do ativo

    @property
    def quoted(self) -> bool:
        return self.asset_type not in NO_LIVE_QUOTE


# --- Arquivo da carteira ------------------------------------------------------

def read_portfolio(path: Path) -> list[Holding]:
    """Lê o CSV aceitando o formato do Excel em português (";" e vírgula decimal)."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")  # "CSV" salvo pelo Excel no Windows

    # ";" é o separador do Excel em português, que também usa vírgula decimal
    excel_ptbr = ";" in text.split("\n", 1)[0]
    reader = csv.DictReader(io.StringIO(text), delimiter=";" if excel_ptbr else ",")
    reader.fieldnames = [normalize(f).strip().replace(" ", "_") for f in reader.fieldnames or []]
    missing = COLUMNS - set(reader.fieldnames)
    if missing:
        raise PortfolioFileError(f"Faltam colunas na carteira: {', '.join(sorted(missing))}.")

    merged: dict[str, Holding] = {}
    for line_no, row in enumerate(reader, start=2):
        if not any((v or "").strip() for v in row.values()):
            continue  # linha em branco
        holding = _parse_row(row, line_no, excel_ptbr)
        if holding.ticker in merged:
            # Mesmo ativo em duas linhas: soma e recalcula o preço médio
            prev = merged[holding.ticker]
            total = prev.quantity + holding.quantity
            prev.avg_price = (prev.avg_price * prev.quantity + holding.avg_price * holding.quantity) / total
            prev.quantity = total
        else:
            merged[holding.ticker] = holding
    return list(merged.values())


def _parse_row(row: dict, line_no: int, excel_ptbr: bool) -> Holding:
    asset_type = ASSET_TYPES.get(normalize(row["tipo"] or "").strip())
    if not asset_type:
        raise PortfolioFileError(
            f"Linha {line_no}: tipo deve ser ação, FII, ETF, BDR, ETF Internacional ou Tesouro Direto."
        )

    raw_ticker = " ".join((row["ticker"] or "").split())
    if asset_type == "Tesouro Direto":
        ticker = raw_ticker  # nome do título, ex.: "Tesouro Selic 2031"
        valid = 0 < len(ticker) <= 60
    else:
        ticker = raw_ticker.upper()
        pattern = US_TICKER_RE if asset_type == "ETF Internacional" else B3_TICKER_RE
        valid = bool(pattern.match(ticker))
    if not valid:
        raise PortfolioFileError(f"Linha {line_no}: ticker inválido ({ticker or 'vazio'}).")

    # Quantidade pode ser fracionada (ex.: 0.75 de um ETF americano)
    quantity = _number(row["quantidade"], line_no, "quantidade", excel_ptbr)
    avg_price = _number(row["preco_medio"], line_no, "preço médio", excel_ptbr)
    if quantity <= 0 or avg_price < 0:
        raise PortfolioFileError(f"Linha {line_no}: quantidade deve ser maior que zero e preço médio não pode ser negativo.")
    return Holding(ticker, asset_type, quantity, avg_price)


THOUSANDS_RE = re.compile(r"[1-9]\d{0,2}(\.\d{3})+")


def _number(text: str | None, line_no: int, column: str, excel_ptbr: bool) -> float:
    """Aceita "32.50" e "32,50"; no formato do Excel em português, também "1.000" e "1.234,56"."""
    value = (text or "").strip().replace("R$", "").replace("US$", "").replace(" ", "")
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    elif excel_ptbr and THOUSANDS_RE.fullmatch(value):
        value = value.replace(".", "")  # "1.000" é mil, não um
    try:
        return float(value)
    except ValueError:
        raise PortfolioFileError(f"Linha {line_no}: {column} inválido ({text!r}).") from None


# --- Cotações -------------------------------------------------------------------

def quote_ttl(currency: str, now: datetime) -> float:
    """30 minutos com o pregão aberto; fechado, até a próxima abertura."""
    tz, opens, closes = MARKET_HOURS.get(currency, MARKET_HOURS["BRL"])
    local = now.astimezone(tz)
    if local.weekday() < 5 and opens <= local.time() < closes:
        return QUOTE_TTL
    day = local.date() if local.weekday() < 5 and local.time() < opens else local.date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    next_open = datetime.combine(day, opens, tzinfo=tz)
    return max(QUOTE_TTL, (next_open - local).total_seconds())


def _quote_key(ticker: str) -> str:
    return f"brapi:quote:{ticker}"


@dataclass
class FetchResult:
    fetched: set[str] = field(default_factory=set)  # cotações atualizadas nesta chamada
    unknown: set[str] = field(default_factory=set)  # tickers que a brapi não reconhece
    stop_reason: str | None = None  # por que as buscas pararam (erro ou cota)


def _fetch_quotes(tickers: list[str], settings: Settings, cache: Cache, http: httpx.Client, token: str) -> FetchResult:
    """Busca as cotações vencidas, uma requisição por vez, e guarda no cache."""
    result = FetchResult()
    size = settings.brapi_tickers_per_request
    for i in range(0, len(tickers), size):
        chunk = tickers[i:i + size]

        quota = cache.get(QUOTA_KEY)
        if quota and quota.value["remaining"] <= quota.value["limit"] * QUOTA_RESERVE:
            result.stop_reason = "Cota da brapi quase no fim: cotações pausadas até ela renovar."
            return result

        try:
            batch = brapi.fetch_quotes(http, token, chunk)
        except ConnectorError as exc:
            if exc.status == 404:
                result.unknown.update(chunk)  # ticker que a brapi não conhece
                continue
            result.stop_reason = str(exc)
            return result

        if batch.quota:
            cache.set(QUOTA_KEY, {"remaining": batch.quota.remaining, "limit": batch.quota.limit}, 86400)
        now = datetime.now(timezone.utc)
        for ticker in chunk:
            quote = batch.quotes.get(ticker)
            if quote is None:
                result.unknown.add(ticker)
                continue
            result.fetched.add(ticker)
            currency = "USD" if quote.currency.upper() == "USD" else "BRL"
            cache.set(_quote_key(ticker), {
                "price": quote.price,
                "change_pct": quote.change_pct,
                "currency": currency,
                "name": quote.short_name,
                "time": (quote.market_time or now).isoformat(),
            }, quote_ttl(currency, now))
    return result


def _usd_brl(cache: Cache, http: httpx.Client, settings: Settings) -> tuple[FxQuote | None, str | None]:
    """Dólar do momento. Se a fonte falhar, usa o último conhecido e avisa."""
    cached = cache.get(FX_KEY)
    if cached:
        return FxQuote(**cached.value), None
    try:
        fx = fetch_usd_brl(http)
    except ConnectorError as exc:
        stale = cache.get_stale(FX_KEY)
        if stale:
            fx = FxQuote(**stale.value)
            return fx, f"{exc} Usando o dólar de {fx.updated_at.astimezone(settings.tz):%H:%M}."
        return None, f"{exc} Ativos em dólar ficam sem conversão para reais."
    cache.set(FX_KEY, fx.model_dump(mode="json"), FX_TTL)
    return fx, None


# --- Coleta compartilhada pelos dois painéis --------------------------------------

@dataclass
class Collected:
    holdings: list[Holding]
    quotes: dict[str, Entry]  # só os ativos com cotação (nova ou do cache)
    fx: FxQuote | None
    fetch: FetchResult
    notes: list[str]


def _collect(settings: Settings, cache: Cache, http: httpx.Client, portfolio_file: Path) -> Collected | PanelResponse:
    """Lê a carteira e garante cotações e dólar. Devolve um PanelResponse se não der para seguir."""
    now = datetime.now(settings.tz)

    def respond(status, message):
        return PanelResponse(status=status, source="live", updated_at=now, message=message)

    if not portfolio_file.exists():
        return respond("not_configured", "Carteira não encontrada: cadastre as suas posições.")
    token = secret(settings.brapi_token)
    if not token:
        return respond("not_configured", "Mercado não configurado: falta o token da brapi (gratuito).")
    try:
        holdings = read_portfolio(portfolio_file)
    except PortfolioFileError as exc:
        return respond("error", str(exc))

    # O painel e o briefing pedem ao mesmo tempo; o lock evita buscas repetidas
    with _lock:
        quoted = [h.ticker for h in holdings if h.quoted]
        expired = [t for t in quoted if not cache.get(_quote_key(t))]
        fetch = _fetch_quotes(expired, settings, cache, http, token) if expired else FetchResult()
        fx, fx_note = _usd_brl(cache, http, settings)

    quotes = {t: e for t in quoted if (e := cache.get_stale(_quote_key(t)))}
    notes = []
    if fetch.stop_reason and quotes:
        oldest = datetime.fromtimestamp(min(e.stored_at for e in quotes.values()), settings.tz)
        notes.append(f"{fetch.stop_reason} Mostrando cotações de {oldest:%H:%M}.")
    elif fetch.stop_reason:
        notes.append(fetch.stop_reason)
    not_recognized = [t for t in quoted if t in fetch.unknown and t not in quotes]
    if not_recognized:
        notes.append(f"A brapi não reconheceu: {', '.join(not_recognized)}.")
    if fx_note:
        notes.append(fx_note)
    return Collected(holdings, quotes, fx, fetch, notes)


def load_market(settings: Settings, cache: Cache, http: httpx.Client, portfolio_file: Path) -> PanelResponse[Market]:
    now = datetime.now(settings.tz)
    collected = _collect(settings, cache, http, portfolio_file)
    if isinstance(collected, PanelResponse):
        return collected
    c = collected

    items = []
    for h in c.holdings:
        entry = c.quotes.get(h.ticker)
        if entry is None:
            note = "Sem cotação ao vivo gratuita." if not h.quoted else (
                "Ticker não reconhecido." if h.ticker in c.fetch.unknown else "Ainda sem cotação.")
            items.append(AssetQuote(ticker=h.ticker, asset_type=h.asset_type, note=note))
            continue
        q = entry.value
        items.append(AssetQuote(
            ticker=h.ticker, asset_type=h.asset_type, name=q.get("name"), currency=q["currency"],
            price=q["price"], change_pct=q["change_pct"],
            quoted_at=datetime.fromisoformat(q["time"]),
        ))

    if not c.fx and not c.quotes:
        return PanelResponse(status="error", source="live", updated_at=now, message=" ".join(c.notes))
    return PanelResponse(
        status="ok", source="live", updated_at=now, message=" ".join(c.notes) or None,
        data=Market(usd_brl=c.fx, quotes=items),
    )


def load_portfolio(settings: Settings, cache: Cache, http: httpx.Client, portfolio_file: Path) -> PanelResponse[Portfolio]:
    """Carteira em reais. Só aparece na aba privada; alimenta o briefing (só em %) e a IA."""
    now = datetime.now(settings.tz)
    collected = _collect(settings, cache, http, portfolio_file)
    if isinstance(collected, PanelResponse):
        return collected
    c = collected

    positions, unquoted, left_out = [], [], []
    for h in c.holdings:
        entry = c.quotes.get(h.ticker)
        q = entry.value if entry else None
        if q is None or (q["currency"] == "USD" and not c.fx):
            # Sem cotação (ou sem dólar para converter): mostra o valor aplicado, fora dos totais
            unquoted.append(UnquotedPosition(
                ticker=h.ticker, asset_type=h.asset_type, quantity=h.quantity, avg_price=h.avg_price))
            if h.quoted:
                left_out.append(h.ticker)  # devia ter cotação: vale um aviso
            continue
        positions.append(Position(
            ticker=h.ticker, asset_type=h.asset_type, quantity=h.quantity, avg_price=h.avg_price,
            price=q["price"], day_change_pct=q["change_pct"], currency=q["currency"],
            fx=c.fx.bid if q["currency"] == "USD" else 1.0,
        ))

    if not positions:
        return PanelResponse(status="error", source="live", updated_at=now,
                             message=" ".join(c.notes) or "Nenhum ativo da carteira tem cotação.")
    notes = list(c.notes)
    if left_out:
        notes.append(f"Fora dos totais (sem cotação): {', '.join(left_out)}.")
    oldest = datetime.fromtimestamp(min(c.quotes[p.ticker].stored_at for p in positions), settings.tz)
    return PanelResponse(
        status="ok",
        source="live" if all(p.ticker in c.fetch.fetched for p in positions) else "cache",
        updated_at=oldest,
        message=" ".join(notes) or None,
        data=Portfolio(positions=positions, unquoted=unquoted),
    )
