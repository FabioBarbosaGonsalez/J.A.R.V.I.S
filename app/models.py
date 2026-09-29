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
    # "unknown": o feed iCal (plano B do Canvas) não informa se foi entregue
    status: Literal["pending", "submitted", "unknown"]
    url: str | None = None

    @property
    def open(self) -> bool:
        """Ainda pode precisar de atenção (não sabemos se foi entregue, ou não foi)."""
        return self.status != "submitted"

    @computed_field
    @property
    def hours_left(self) -> float:
        # Arredonda para baixo, como uma contagem regressiva (igual ao painel)
        now = datetime.now(self.due_at.tzinfo)
        return math.floor((self.due_at - now).total_seconds() / 360) / 10

    @computed_field
    @property
    def urgent(self) -> bool:
        """Em aberto e com prazo nas próximas 48 horas."""
        return self.open and 0 < self.hours_left < 48


# --- Investimentos --------------------------------------------------------

AssetType = Literal["ação", "FII", "ETF", "BDR", "ETF Internacional", "Tesouro Direto"]


class Position(BaseModel):
    """Posição com preço e preço médio na moeda do ativo (R$ ou US$).

    `fx` converte para reais: 1 para ativos da B3, o dólar do momento para os
    dos EUA. Valores em R$ usam o câmbio atual, então o resultado sobre o preço
    médio mede o ativo, sem o efeito da variação do dólar desde a compra.
    """

    ticker: str
    asset_type: AssetType
    quantity: float
    avg_price: float
    price: float
    day_change_pct: float
    currency: Literal["BRL", "USD"] = "BRL"
    fx: float = 1.0

    @computed_field
    @property
    def market_value(self) -> float:
        return round(self.quantity * self.price * self.fx, 2)

    @computed_field
    @property
    def cost(self) -> float:
        return round(self.quantity * self.avg_price * self.fx, 2)

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


# --- Mercado (painel da home: dólar e cotações, sem valores da carteira) ----

class FxQuote(BaseModel):
    pair: str  # "USD-BRL"
    bid: float  # preço de compra do dólar comercial, em R$
    pct_change: float
    high: float
    low: float
    updated_at: datetime


class AssetQuote(BaseModel):
    """Cotação de um ativo da carteira. Sem quantidade nem valor investido."""

    ticker: str
    asset_type: AssetType
    name: str | None = None
    currency: Literal["BRL", "USD"] | None = None
    price: float | None = None  # na moeda do ativo: R$ na B3, US$ nos EUA
    change_pct: float | None = None
    quoted_at: datetime | None = None
    note: str | None = None  # por que não há cotação, quando não há


class Market(BaseModel):
    usd_brl: FxQuote | None = None
    quotes: list[AssetQuote] = []


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
