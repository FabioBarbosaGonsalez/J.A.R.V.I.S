"""Ações com confirmação: a IA só propõe; você confirma com um clique.

- A proposta fica na memória do servidor, com um identificador aleatório,
  expira em poucos minutos e só pode ser usada uma vez.
- Nada é gravado antes do clique em Confirmar. A IA não tem ferramenta para
  confirmar, então dizer "confirmo" no chat ou por voz não grava nada.
- Evento: criado só na agenda principal. Ativo: só com a aba "Minha carteira"
  desbloqueada, e os detalhes (quantidade, preço, efeito na carteira) só
  aparecem lá.
- Cada ação confirmada entra num histórico local (fora do Git).
- No modo demonstração, nada é gravado de verdade.
"""

import json
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app import sources
from app.config import DATA_DIR, Settings
from app.connectors import demo, gcalendar, portfolio_write
from app.connectors.investments import Holding, read_portfolio
from app.formatting import WEEKDAYS
from app.models import ActionCard, AssetDraft, AssetPreview, EventDraft

ACTION_TTL = 5 * 60  # segundos até o cartão expirar
HISTORY_FILE = DATA_DIR / "historico_acoes.jsonl"


@dataclass
class Proposal:
    id: str
    kind: Literal["event", "asset"]
    expires_at: datetime
    event: EventDraft | None = None
    asset: AssetDraft | None = None

    def card(self) -> ActionCard:
        """Cartão do chat. O de ativo leva só o ticker: nada de números fora da aba privada."""
        return ActionCard(
            id=self.id, kind=self.kind, expires_at=self.expires_at,
            event=self.event, ticker=self.asset.ticker if self.asset else None,
        )


class ActionStore:
    def __init__(self, ttl: float = ACTION_TTL, clock=time.time):
        self.ttl = ttl
        self._clock = clock
        self._items: dict[str, tuple[Proposal, float]] = {}
        self._lock = threading.Lock()

    def _purge(self) -> None:
        now = self._clock()
        for key in [k for k, (_, deadline) in self._items.items() if deadline <= now]:
            del self._items[key]

    def propose(self, now: datetime, *, event: EventDraft | None = None, asset: AssetDraft | None = None) -> Proposal:
        proposal = Proposal(
            id=secrets.token_urlsafe(16), kind="event" if event else "asset",
            expires_at=now + timedelta(seconds=self.ttl), event=event, asset=asset,
        )
        with self._lock:
            self._purge()
            self._items[proposal.id] = (proposal, self._clock() + self.ttl)
        return proposal

    def get(self, action_id: str) -> Proposal | None:
        with self._lock:
            self._purge()
            item = self._items.get(action_id)
            return item[0] if item else None

    def pending(self, kind: str) -> list[Proposal]:
        with self._lock:
            self._purge()
            return [p for p, _ in self._items.values() if p.kind == kind]

    def take(self, action_id: str) -> Proposal | None:
        """Retira a proposta para executar: uma segunda confirmação não acha mais nada."""
        with self._lock:
            self._purge()
            item = self._items.pop(action_id, None)
            return item[0] if item else None

    def restore(self, proposal: Proposal) -> None:
        """Devolve a proposta quando a execução falhou sem gravar nada (dá para tentar de novo)."""
        with self._lock:
            remaining = (proposal.expires_at - datetime.now(proposal.expires_at.tzinfo)).total_seconds()
            if remaining > 0:
                self._items[proposal.id] = (proposal, self._clock() + remaining)

    def cancel(self, action_id: str) -> bool:
        return self.take(action_id) is not None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


store = ActionStore()


# --- Textos --------------------------------------------------------------------

def describe_event(draft: EventDraft) -> str:
    """'Estudo de Cálculo, quarta 30/09 das 19:00 às 20:00' (usado no resumo e no histórico)."""
    day = f"{WEEKDAYS[draft.start.weekday()]} {draft.start:%d/%m/%Y}"
    if draft.all_day:
        return f"{draft.title}, {day}, dia inteiro"
    return f"{draft.title}, {day} das {draft.start:%H:%M} às {draft.end:%H:%M}"


def record(kind: str, summary: str, now: datetime) -> None:
    """Histórico local das ações confirmadas: data, tipo e resumo, uma por linha."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"quando": now.isoformat(timespec="seconds"), "tipo": kind, "resumo": summary},
                      ensure_ascii=False)
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# --- Carteira ------------------------------------------------------------------

def current_holdings(settings: Settings) -> list[Holding]:
    if settings.demo_mode:
        pf = demo.portfolio(settings.tz)
        return [Holding(p.ticker, p.asset_type, p.quantity, p.avg_price) for p in pf.positions] + \
               [Holding(u.ticker, u.asset_type, u.quantity, u.avg_price) for u in pf.unquoted]
    path = sources.PORTFOLIO_FILE
    return read_portfolio(path) if path.exists() else []


def asset_preview(proposal: Proposal, settings: Settings) -> AssetPreview:
    """O que muda na carteira. Só para a aba privada desbloqueada."""
    draft = proposal.asset
    preview = AssetPreview(
        id=proposal.id, expires_at=proposal.expires_at, draft=draft,
        currency="USD" if draft.asset_type == "ETF Internacional" else "BRL",
    )
    try:
        plan = portfolio_write.plan_add(current_holdings(settings), draft)
    except portfolio_write.PortfolioFileError as exc:
        preview.problem = str(exc)
        return preview
    preview.exists = plan.exists
    if plan.current:
        preview.current_quantity = plan.current.quantity
        preview.current_avg_price = plan.current.avg_price
    preview.new_quantity = plan.new_quantity
    preview.new_avg_price = plan.new_avg_price
    return preview


def confirm_asset(proposal: Proposal, settings: Settings, now: datetime) -> str:
    """Grava o ativo. Erros sobem como `PortfolioFileError`, sem ter alterado nada."""
    draft = proposal.asset
    if settings.demo_mode:
        # Valida do mesmo jeito, mas não grava
        portfolio_write.plan_add(current_holdings(settings), draft)
        return f"Modo demonstração: {draft.ticker} não foi gravado de verdade."
    path = sources.PORTFOLIO_FILE
    plan = portfolio_write.add_holding(path, draft, path.parent / "backups", now)
    verb = "somado à posição existente" if plan.exists else "inserido"
    record("ativo", f"{draft.ticker} ({draft.asset_type}): {verb}, +{draft.quantity:g} a {draft.price:g}", now)
    return f"{draft.ticker} {verb} na carteira."


# --- Agenda --------------------------------------------------------------------

def confirm_event(proposal: Proposal, settings: Settings, now: datetime) -> str:
    """Cria o evento. Erros sobem como `GoogleNotReady` ou `ConnectorError`."""
    draft = proposal.event
    if settings.demo_mode:
        return "Modo demonstração: o evento não foi criado de verdade."
    gcalendar.create_event(draft, settings, sources.get_cache(), sources.get_google_auth(settings))
    summary = describe_event(draft)
    record("evento", summary, now)
    return f"Evento criado na sua agenda: {summary}."
