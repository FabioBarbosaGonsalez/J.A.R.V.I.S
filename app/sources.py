"""Ponto único onde cada painel obtém seus dados.

Com DEMO_MODE=true, tudo vem de `connectors.demo`. Sem ele, cada função chama o
conector real e devolve o mesmo `PanelResponse`, então as rotas e o front-end
não mudam. Gmail e Agenda chegam na Fase 3.

A carteira e o mercado compartilham o cache: chamar os dois não duplica
requisições à brapi.
"""

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

import httpx

from app.cache import Cache
from app.config import CACHE_FILE, PORTFOLIO_FILE, Settings
from app.connectors import canvas, demo, investments
from app.connectors.http import read_only_client
from app.models import CalendarEvent, Deliverable, Email, Market, PanelResponse, Portfolio


@lru_cache
def get_cache() -> Cache:
    return Cache(CACHE_FILE)


@lru_cache
def get_http() -> httpx.Client:
    return read_only_client()


def _ok(data, settings: Settings) -> PanelResponse:
    return PanelResponse(status="ok", source="demo", updated_at=datetime.now(settings.tz), data=data)


def _not_configured(message: str, settings: Settings) -> PanelResponse:
    return PanelResponse(status="not_configured", updated_at=datetime.now(settings.tz), message=message)


def emails_panel(settings: Settings) -> PanelResponse[list[Email]]:
    if settings.demo_mode:
        return _ok(demo.emails(settings.tz), settings)
    return _not_configured("A integração com o Gmail chega na Fase 3.", settings)


def calendar_panel(settings: Settings) -> PanelResponse[list[CalendarEvent]]:
    if settings.demo_mode:
        return _ok(demo.calendar_events(settings.tz), settings)
    return _not_configured("A integração com o Google Calendar chega na Fase 3.", settings)


def canvas_panel(settings: Settings, force: bool = False) -> PanelResponse[list[Deliverable]]:
    if settings.demo_mode:
        return _ok(demo.deliverables(settings.tz), settings)
    return canvas.load(settings, get_cache(), get_http(), force=force)


def portfolio_panel(settings: Settings) -> PanelResponse[Portfolio]:
    """Carteira em reais: fica fora da home, alimenta o briefing (só em %) e a IA."""
    if settings.demo_mode:
        return _ok(demo.portfolio(settings.tz), settings)
    return investments.load_portfolio(settings, get_cache(), get_http(), PORTFOLIO_FILE)


def market_panel(settings: Settings) -> PanelResponse[Market]:
    """Painel da home: dólar ao vivo e cotações dos ativos, sem valores investidos."""
    if settings.demo_mode:
        return _ok(demo.market(settings.tz), settings)
    return investments.load_market(settings, get_cache(), get_http(), PORTFOLIO_FILE)


@dataclass
class Snapshot:
    """O que o assistente sabe agora. Fontes indisponíveis ficam como None."""

    emails: list[Email] | None
    events: list[CalendarEvent] | None
    deliverables: list[Deliverable] | None
    portfolio: Portfolio | None
    market: Market | None = None


def snapshot(settings: Settings) -> Snapshot:
    def data_or_none(panel: PanelResponse):
        return panel.data if panel.status == "ok" else None

    return Snapshot(
        emails=data_or_none(emails_panel(settings)),
        events=data_or_none(calendar_panel(settings)),
        deliverables=data_or_none(canvas_panel(settings)),
        portfolio=data_or_none(portfolio_panel(settings)),
        market=data_or_none(market_panel(settings)),
    )
