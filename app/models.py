"""Schemas Pydantic compartilhados pela API, pelos conectores e (na Fase 4) pela IA.

Os dados falsos da Fase 1 usam exatamente estes modelos. Assim, quando as
integrações reais entrarem, só a origem dos dados muda e o front-end continua igual.
"""

import math
from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field, computed_field

T = TypeVar("T")

PanelStatus = Literal["ok", "not_configured", "error"]
DataSource = Literal["demo", "live", "cache"]


class PanelResponse(BaseModel, Generic[T]):
    """Envelope de todo painel.

    O `status` permite que cada painel falhe sozinho: o front-end mostra
    "não configurado" ou "erro — tentar de novo" sem afetar os outros.
    """

    status: PanelStatus = "ok"
    source: DataSource = "demo"
    updated_at: datetime
    message: str | None = None
    data: T | None = None


# --- E-mail ---------------------------------------------------------------

class Email(BaseModel):
    id: str
    sender_name: str
    sender_email: str
    subject: str
    snippet: str
    received_at: datetime
    unread: bool
    from_university: bool = False


# --- Agenda ---------------------------------------------------------------

class CalendarEvent(BaseModel):
    id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str | None = None


# --- Faculdade (Canvas) ---------------------------------------------------

class Deliverable(BaseModel):
    id: str
    title: str
    course: str
    due_at: datetime  # sempre com fuso horário
    status: Literal["pending", "submitted"]
    url: str | None = None

    @computed_field
    @property
    def hours_left(self) -> float:
        # Arredonda para baixo, como uma contagem regressiva (igual ao painel)
        now = datetime.now(self.due_at.tzinfo)
        return math.floor((self.due_at - now).total_seconds() / 360) / 10

    @computed_field
    @property
    def urgent(self) -> bool:
        """Pendente e com prazo nas próximas 48 horas."""
        return self.status == "pending" and 0 < self.hours_left < 48


# --- Investimentos --------------------------------------------------------

AssetType = Literal["ação", "FII", "ETF", "BDR"]


class Position(BaseModel):
    ticker: str
    asset_type: AssetType
    quantity: float
    avg_price: float
    price: float
    day_change_pct: float

    @computed_field
    @property
    def market_value(self) -> float:
        return round(self.quantity * self.price, 2)

    @computed_field
    @property
    def cost(self) -> float:
        return round(self.quantity * self.avg_price, 2)

    @computed_field
    @property
    def result_value(self) -> float:
        return round(self.market_value - self.cost, 2)

    @computed_field
    @property
    def result_pct(self) -> float:
        return round(self.result_value / self.cost * 100, 2) if self.cost else 0.0

    @computed_field
    @property
    def day_change_value(self) -> float:
        previous = self.market_value / (1 + self.day_change_pct / 100)
        return round(self.market_value - previous, 2)


class Dividend(BaseModel):
    ticker: str
    kind: Literal["Dividendo", "JCP", "Rendimento"]
    value_per_share: float
    payment_date: date
    estimated_total: float


class Allocation(BaseModel):
    asset_type: AssetType
    value: float
    pct: float


class Portfolio(BaseModel):
    positions: list[Position]
    dividends: list[Dividend] = []

    @computed_field
    @property
    def total_value(self) -> float:
        return round(sum(p.market_value for p in self.positions), 2)

    @computed_field
    @property
    def total_cost(self) -> float:
        return round(sum(p.cost for p in self.positions), 2)

    @computed_field
    @property
    def result_value(self) -> float:
        return round(self.total_value - self.total_cost, 2)

    @computed_field
    @property
    def result_pct(self) -> float:
        return round(self.result_value / self.total_cost * 100, 2) if self.total_cost else 0.0

    @computed_field
    @property
    def day_change_value(self) -> float:
        return round(sum(p.day_change_value for p in self.positions), 2)

    @computed_field
    @property
    def day_change_pct(self) -> float:
        previous = self.total_value - self.day_change_value
        return round(self.day_change_value / previous * 100, 2) if previous else 0.0

    @computed_field
    @property
    def allocation(self) -> list[Allocation]:
        totals: dict[str, float] = {}
        for p in self.positions:
            totals[p.asset_type] = totals.get(p.asset_type, 0.0) + p.market_value
        total = self.total_value or 1.0
        items = [
            Allocation(asset_type=t, value=round(v, 2), pct=round(v / total * 100, 1))
            for t, v in totals.items()
        ]
        return sorted(items, key=lambda a: a.value, reverse=True)


# --- Briefing e chat ------------------------------------------------------

class Highlight(BaseModel):
    level: Literal["info", "warning", "critical"]
    text: str


class Briefing(BaseModel):
    text: str
    highlights: list[Highlight] = []
    generated_at: datetime
    generator: Literal["rules", "ai"] = "rules"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    reply: str
    generator: Literal["demo", "ai"] = "demo"


class StatusResponse(BaseModel):
    assistant_name: str
    user_name: str
    demo_mode: bool
    refresh_seconds: int
    voice_lang: str = "pt-BR"
    version: str
