"""Ponto único onde cada painel obtém seus dados.

Na Fase 1 tudo vem de `connectors.demo`. Nas próximas fases, cada função passa
a chamar o conector real (Canvas, brapi, Gmail, Calendar) e continua devolvendo
o mesmo `PanelResponse`, então as rotas e o front-end não mudam.
"""

from dataclasses import dataclass
from datetime import datetime

from app.config import Settings
from app.connectors import demo
from app.models import CalendarEvent, Deliverable, Email, PanelResponse, Portfolio


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


def canvas_panel(settings: Settings) -> PanelResponse[list[Deliverable]]:
    if settings.demo_mode:
        return _ok(demo.deliverables(settings.tz), settings)
    return _not_configured("A integração com o Canvas chega na Fase 2.", settings)


def portfolio_panel(settings: Settings) -> PanelResponse[Portfolio]:
    if settings.demo_mode:
        return _ok(demo.portfolio(settings.tz), settings)
    return _not_configured("A integração com a brapi chega na Fase 2.", settings)


@dataclass
class Snapshot:
    """O que o assistente sabe agora. Fontes indisponíveis ficam como None."""

    emails: list[Email] | None
    events: list[CalendarEvent] | None
    deliverables: list[Deliverable] | None
    portfolio: Portfolio | None


def snapshot(settings: Settings) -> Snapshot:
    def data_or_none(panel: PanelResponse):
        return panel.data if panel.status == "ok" else None

    return Snapshot(
        emails=data_or_none(emails_panel(settings)),
        events=data_or_none(calendar_panel(settings)),
        deliverables=data_or_none(canvas_panel(settings)),
        portfolio=data_or_none(portfolio_panel(settings)),
    )
