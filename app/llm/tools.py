"""Ferramentas que o modelo de IA pode chamar.

Leitura (agenda, e-mails, faculdade, carteira) e duas de proposta
(`propor_evento`, `propor_ativo`), que só criam um cartão de confirmação:
nada é gravado antes do clique em Confirmar (ver `app.actions`).

Cada ferramenta devolve um resumo curto, não o objeto inteiro: menos tokens
gastos da cota gratuita e menos conteúdo pessoal enviado ao Google.

- E-mails: remetente (só o nome), assunto e data. Nunca o corpo nem o endereço.
- Agenda e faculdade: título, datas e disciplina. Nunca links.
- Carteira: só percentuais e cotações públicas. Nunca valores em reais nem
  quantidades, porque a resposta é falada e aparece na tela inicial, fora da
  aba privada. Ao propor um ativo, o modelo nem fica sabendo se ele já existe.
"""

import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any

from app import actions, sources
from app.config import Settings
from app.connectors import portfolio_write
from app.connectors.gcalendar import DAYS_AHEAD
from app.formatting import WEEKDAYS, duration
from app.llm.provider import Tool, ToolExecutor, tool_result
from app.models import ActionCard, CalendarEvent, EventDraft, PanelResponse

MAX_EMAILS = 20
MAX_EVENT_MINUTES = 24 * 60
MAX_DAYS_AHEAD = 2 * 365
DEFAULT_EVENT_MINUTES = 60
ASSET_TYPE_NAMES = ["ação", "FII", "ETF", "BDR", "ETF Internacional", "Tesouro Direto"]
# "19:00", "19h", "19h30", "7"
TIME_RE = re.compile(r"^\s*(\d{1,2})\s*(?:[:h]\s*(\d{2})?)?\s*$", re.IGNORECASE)


TOOLS = [
    Tool(
        name="listar_eventos",
        description=(
            "Lista os compromissos da agenda do Google entre duas datas (inclusive). "
            f"A agenda só cobre de hoje até {DAYS_AHEAD} dias à frente."
        ),
        parameters={
            "type": "object",
            "properties": {
                "data_inicial": {"type": "string", "description": "AAAA-MM-DD. Padrão: hoje."},
                "data_final": {"type": "string", "description": "AAAA-MM-DD. Padrão: a data inicial."},
            },
        },
    ),
    Tool(
        name="listar_emails",
        description=(
            "Lista os e-mails recentes da caixa de entrada: remetente, assunto, data e se foi lido. "
            "Não inclui o corpo das mensagens."
        ),
        parameters={
            "type": "object",
            "properties": {
                "apenas_nao_lidos": {"type": "boolean", "description": "Padrão: false."},
                "apenas_faculdade": {"type": "boolean", "description": "Só remetentes da faculdade. Padrão: false."},
                "limite": {"type": "integer", "description": f"Máximo de e-mails (1 a {MAX_EMAILS}). Padrão: 10."},
            },
        },
    ),
    Tool(
        name="listar_entregas",
        description="Lista as entregas (tarefas e provas) da faculdade no Canvas, da mais próxima para a mais distante.",
        parameters={
            "type": "object",
            "properties": {
                "incluir_entregues": {"type": "boolean", "description": "Inclui as já entregues. Padrão: false."},
            },
        },
    ),
    Tool(
        name="resumo_carteira",
        description=(
            "Resumo da carteira de investimentos e do mercado: dólar, variação da carteira em percentual, "
            "cotação e variação de cada ativo e próximos proventos. Não traz valores investidos."
        ),
    ),
]


WRITE_TOOLS = [
    Tool(
        name="propor_evento",
        description=(
            "Propõe criar um compromisso na agenda principal do Google. Não cria nada: mostra um cartão "
            "e só o clique do usuário em Confirmar grava o evento. Sem hora_inicio, o evento é de dia inteiro."
        ),
        parameters={
            "type": "object",
            "properties": {
                "titulo": {"type": "string", "description": "Título curto do evento."},
                "data": {"type": "string", "description": "AAAA-MM-DD."},
                "hora_inicio": {"type": "string", "description": "HH:MM, 24 horas. Omita para dia inteiro."},
                "duracao_minutos": {
                    "type": "integer",
                    "description": f"Duração em minutos (5 a {MAX_EVENT_MINUTES}). Padrão: {DEFAULT_EVENT_MINUTES}.",
                },
            },
            "required": ["titulo", "data"],
        },
    ),
    Tool(
        name="propor_ativo",
        description=(
            "Propõe inserir um ativo na carteira de investimentos. Não grava nada: a confirmação fica "
            "na aba privada Minha carteira. Se o ativo já existir, a quantidade é somada e o preço médio recalculado."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ex.: MXRF11, PETR4, VOO, ou o nome do título do Tesouro."},
                "tipo": {"type": "string", "enum": ASSET_TYPE_NAMES},
                "quantidade": {"type": "number", "description": "Quantidade comprada (maior que zero)."},
                "preco_medio": {
                    "type": "number",
                    "description": "Preço pago por unidade, na moeda do ativo (US$ para ETF Internacional).",
                },
            },
            "required": ["ticker", "tipo", "quantidade", "preco_medio"],
        },
    ),
]
CHAT_TOOLS = TOOLS + WRITE_TOOLS


class ToolArgumentError(ValueError):
    """Argumento inválido vindo do modelo. A mensagem volta para ele corrigir."""


def _when(dt: datetime) -> str:
    """'2026-09-30 (quarta) 19:00': com o dia da semana, o modelo não precisa calcular."""
    return f"{dt:%Y-%m-%d} ({WEEKDAYS[dt.weekday()]}) {dt:%H:%M}"


def _day(d: date) -> str:
    return f"{d:%Y-%m-%d} ({WEEKDAYS[d.weekday()]})"


def _all_day_end(ev: CalendarEvent, tz) -> str | None:
    """Último dia de um evento de dia inteiro que dura mais de um dia (o fim do Google é exclusivo)."""
    last = (ev.end.astimezone(tz) - timedelta(days=1)).date()
    return _day(last) if last > ev.start.astimezone(tz).date() else None


def _date_arg(args: dict[str, Any], name: str, default: date) -> date:
    value = args.get(name)
    if value in (None, ""):
        return default
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ToolArgumentError(f"'{name}' deve estar no formato AAAA-MM-DD.") from None


def _bool_arg(args: dict[str, Any], name: str) -> bool:
    return args.get(name) is True


def _unavailable(panel: PanelResponse) -> dict[str, Any] | None:
    if panel.status == "ok" and panel.data is not None:
        return None
    reason = {"not_configured": "não configurado"}.get(panel.status, "indisponível agora")
    return {"indisponivel": reason}


def listar_eventos(settings: Settings, now: datetime, args: dict[str, Any]) -> dict[str, Any]:
    start = _date_arg(args, "data_inicial", now.date())
    end = _date_arg(args, "data_final", start)
    if end < start:
        start, end = end, start

    panel = sources.calendar_panel(settings)
    if missing := _unavailable(panel):
        return missing

    tz = settings.tz
    window_start = datetime.combine(start, time(0), tzinfo=tz)
    # O fim é exclusivo, como na API do Google: um evento de dia inteiro
    # de ontem termina hoje à 00:00 e não deve aparecer hoje.
    window_end = datetime.combine(end + timedelta(days=1), time(0), tzinfo=tz)
    last_day = now.date() + timedelta(days=DAYS_AHEAD)
    events = [
        {
            "titulo": ev.title,
            "inicio": _day(ev.start.astimezone(tz).date()) if ev.all_day else _when(ev.start.astimezone(tz)),
            "fim": _all_day_end(ev, tz) if ev.all_day else _when(ev.end.astimezone(tz)),
            "dia_inteiro": ev.all_day or None,
            "local": ev.location,
        }
        for ev in panel.data
        # Evento que cruza o intervalo conta (ex.: começou ontem e termina hoje)
        if ev.start < window_end and (ev.end > window_start or ev.start >= window_start)
    ]
    result: dict[str, Any] = {
        "periodo": f"{_day(start)} a {_day(end)}",
        "eventos": [{k: v for k, v in e.items() if v is not None} for e in events],
    }
    if end > last_day or start < now.date():
        result["aviso"] = f"A agenda só cobre de {_day(now.date())} a {_day(last_day)}."
    return tool_result(result)


def listar_emails(settings: Settings, now: datetime, args: dict[str, Any]) -> dict[str, Any]:
    try:
        limit = int(args.get("limite") or 10)
    except (TypeError, ValueError):
        raise ToolArgumentError("'limite' deve ser um número inteiro.") from None
    limit = max(1, min(MAX_EMAILS, limit))

    panel = sources.emails_panel(settings)
    if missing := _unavailable(panel):
        return missing

    emails = panel.data
    if _bool_arg(args, "apenas_nao_lidos"):
        emails = [e for e in emails if e.unread]
    if _bool_arg(args, "apenas_faculdade"):
        emails = [e for e in emails if e.from_university]

    return tool_result({
        "total_encontrado": len(emails),
        "nao_lidos_na_caixa": sum(e.unread for e in panel.data),
        "emails": [
            {
                "de": e.sender_name,
                "assunto": e.subject,
                "recebido": _when(e.received_at.astimezone(settings.tz)),
                "lido": not e.unread,
                "faculdade": e.from_university,
            }
            for e in emails[:limit]
        ],
    })


STATUS = {"pending": "pendente", "submitted": "entregue", "unknown": "não se sabe se foi entregue"}


def listar_entregas(settings: Settings, now: datetime, args: dict[str, Any]) -> dict[str, Any]:
    panel = sources.canvas_panel(settings)
    if missing := _unavailable(panel):
        return missing

    items = [d for d in panel.data if d.hours_left > 0]
    if not _bool_arg(args, "incluir_entregues"):
        items = [d for d in items if d.open]
    items.sort(key=lambda d: d.due_at)

    return tool_result({"entregas": [
        {
            "titulo": d.title,
            "disciplina": d.course,
            "prazo": _when(d.due_at.astimezone(settings.tz)),
            "faltam": duration(d.hours_left),
            "situacao": STATUS[d.status],
            "urgente": d.urgent,
        }
        for d in items
    ]})


def resumo_carteira(settings: Settings, now: datetime, args: dict[str, Any]) -> dict[str, Any]:
    market = sources.market_panel(settings)
    portfolio = sources.portfolio_panel(settings)
    if _unavailable(market) and _unavailable(portfolio):
        return {"indisponivel": "carteira e mercado indisponíveis agora"}

    result: dict[str, Any] = {}
    if market.status == "ok" and market.data:
        fx = market.data.usd_brl
        if fx:
            result["dolar"] = {"cotacao_reais": fx.bid, "variacao_dia_pct": fx.pct_change}
        result["ativos"] = [
            {k: v for k, v in {
                "ticker": q.ticker,
                "tipo": q.asset_type,
                "preco": q.price,
                "moeda": q.currency,
                "variacao_dia_pct": q.change_pct,
                "sem_cotacao": q.note if q.price is None else None,
            }.items() if v is not None}
            for q in market.data.quotes
        ]
    if portfolio.status == "ok" and portfolio.data and portfolio.data.positions:
        p = portfolio.data
        result["carteira"] = {
            "variacao_dia_pct": p.day_change_pct,
            "resultado_sobre_preco_medio_pct": p.result_pct,
            "alocacao_pct": {a.asset_type: a.pct for a in p.allocation},
        }
        upcoming = sorted((d for d in p.dividends if d.payment_date >= now.date()), key=lambda d: d.payment_date)
        if upcoming:
            result["proximos_proventos"] = [
                {"ticker": d.ticker, "tipo": d.kind, "valor_por_cota": d.value_per_share, "pagamento": _day(d.payment_date)}
                for d in upcoming[:5]
            ]
    return tool_result(result)


# --- Propostas (nada é gravado aqui) ---------------------------------------------

NOT_SAVED = (
    "Nada foi gravado ainda. O usuário precisa clicar em Confirmar no cartão que apareceu na tela. "
    "Confirmação por voz ou por texto não vale, e você não consegue confirmar por ele."
)


def _time_arg(value: Any) -> time:
    match = TIME_RE.match(str(value))
    hour, minute = (int(match.group(1)), int(match.group(2) or 0)) if match else (99, 0)
    if hour > 23 or minute > 59:
        raise ToolArgumentError("'hora_inicio' deve estar no formato HH:MM (24 horas).")
    return time(hour, minute)


def propor_evento(settings: Settings, now: datetime, args: dict[str, Any], cards: list[ActionCard]) -> dict[str, Any]:
    title = " ".join(str(args.get("titulo") or "").split())
    if not title:
        raise ToolArgumentError("Informe o 'titulo' do evento.")
    if len(title) > 200:
        raise ToolArgumentError("O 'titulo' deve ter no máximo 200 caracteres.")
    if not args.get("data"):
        raise ToolArgumentError("Informe a 'data' do evento (AAAA-MM-DD).")
    day = _date_arg(args, "data", now.date())
    if day > now.date() + timedelta(days=MAX_DAYS_AHEAD):
        raise ToolArgumentError("A data está longe demais (máximo de dois anos).")

    tz = settings.tz
    if args.get("hora_inicio") in (None, ""):
        if day < now.date():
            raise ToolArgumentError("Essa data já passou.")
        start = datetime.combine(day, time(0), tzinfo=tz)
        draft = EventDraft(title=title, start=start, end=start + timedelta(days=1), all_day=True)
    else:
        start = datetime.combine(day, _time_arg(args["hora_inicio"]), tzinfo=tz)
        if start < now - timedelta(minutes=1):
            raise ToolArgumentError("Esse horário já passou.")
        try:
            minutes = int(args.get("duracao_minutos") or DEFAULT_EVENT_MINUTES)
        except (TypeError, ValueError):
            raise ToolArgumentError("'duracao_minutos' deve ser um número inteiro.") from None
        if not 5 <= minutes <= MAX_EVENT_MINUTES:
            raise ToolArgumentError(f"'duracao_minutos' deve ficar entre 5 e {MAX_EVENT_MINUTES}.")
        draft = EventDraft(title=title, start=start, end=start + timedelta(minutes=minutes))

    cards.append(actions.store.propose(now, event=draft).card())
    return tool_result({"proposta_criada": True, "evento": actions.describe_event(draft), "aviso": NOT_SAVED})


def propor_ativo(settings: Settings, now: datetime, args: dict[str, Any], cards: list[ActionCard]) -> dict[str, Any]:
    try:
        quantity = float(args.get("quantidade"))
        price = float(args.get("preco_medio"))
        draft = portfolio_write.draft_from(args.get("ticker"), args.get("tipo"), quantity, price)
    except (TypeError, ValueError):
        raise ToolArgumentError("'quantidade' e 'preco_medio' devem ser números.") from None
    except portfolio_write.PortfolioFileError as exc:
        text = str(exc)
        raise ToolArgumentError(text[:1].upper() + text[1:]) from None

    cards.append(actions.store.propose(now, asset=draft).card())
    return tool_result({
        "proposta_criada": True,
        "ativo": draft.ticker,
        "aviso": NOT_SAVED + " Os detalhes e o botão Confirmar ficam na aba Minha carteira, protegida por chave. "
                 "Não repita quantidade, preço nem valores na resposta, porque ela é falada em voz alta.",
    })


WRITE_HANDLERS = {"propor_evento": propor_evento, "propor_ativo": propor_ativo}
assert set(WRITE_HANDLERS) == {t.name for t in WRITE_TOOLS}


HANDLERS: dict[str, Callable[[Settings, datetime, dict[str, Any]], dict[str, Any]]] = {
    "listar_eventos": listar_eventos,
    "listar_emails": listar_emails,
    "listar_entregas": listar_entregas,
    "resumo_carteira": resumo_carteira,
}
assert set(HANDLERS) == {t.name for t in TOOLS}


def make_executor(settings: Settings, now: datetime, cards: list[ActionCard] | None = None) -> ToolExecutor:
    """Executor para o provedor: chama a ferramenta pelo nome e trata argumentos ruins.

    As ferramentas de proposta só funcionam com `cards`, a lista que recebe os
    cartões de confirmação para mostrar no chat.
    """

    def execute(name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            if name in HANDLERS:
                return HANDLERS[name](settings, now, args)
            if name in WRITE_HANDLERS and cards is not None:
                return WRITE_HANDLERS[name](settings, now, args, cards)
        except ToolArgumentError as exc:
            return {"erro": str(exc)}
        return {"erro": f"Ferramenta desconhecida: {name}."}

    return execute
