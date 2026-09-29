"""Chat em modo demonstração.

Respostas por palavras-chave, só para testar o fluxo de texto e voz na Fase 1.
Na Fase 4, o modelo de IA decide quais ferramentas chamar; esta função some.
As respostas são escritas para serem faladas: frases curtas, sem símbolos, no
tom de um mordomo educado e direto (texto próprio, nada copiado de filmes).
"""

import re
from datetime import datetime

from app.formatting import brl, duration, normalize, pct, plural
from app.models import CalendarEvent
from app.sources import Snapshot

# A ordem importa: o primeiro tópico que casar vence.
# Palavras soltas casam pelo início da palavra ("mensage" -> "mensagens").
TOPICS = {
    "advice": ("devo comprar", "devo vender", "vale a pena comprar", "recomenda"),
    "deliverables": ("entrega", "prazo", "faculdade", "canvas", "tarefa", "trabalho", "prova"),
    "emails": ("email", "mensage", "caixa de entrada"),
    "portfolio": ("carteira", "investimento", "acoes", "fii", "dividendo", "provento",
                  "dolar", "cambio", "cotac", "mercado", "bolsa"),
    "calendar": ("agenda", "compromisso", "evento", "reuniao", "amanha", "hoje"),
    "greeting": ("ola", "oi", "bom dia", "boa tarde", "boa noite"),
}


def _topic(message: str) -> str | None:
    text = normalize(message).replace("e-mail", "email")
    words = re.findall(r"[a-z0-9]+", text)
    for topic, keywords in TOPICS.items():
        for keyword in keywords:
            if " " in keyword:
                if keyword in text:
                    return topic
            elif any(word.startswith(keyword) for word in words):
                return topic
    return None


def _event_when(ev: CalendarEvent, now: datetime) -> str:
    if ev.all_day:
        return "dia inteiro"
    if ev.start <= now:
        return f"em andamento até as {ev.end:%H:%M}"
    return ev.start.strftime("%d/%m às %H:%M")


def _market_reply(snap: Snapshot) -> str:
    """Dólar, variação da carteira e destaques do dia. Nunca o valor investido."""
    parts = []
    market = snap.market
    if market and market.usd_brl:
        parts.append(f"O dólar está a {brl(market.usd_brl.bid)}, {pct(market.usd_brl.pct_change)} no dia.")
    if snap.portfolio and snap.portfolio.positions:
        p = snap.portfolio
        parts.append(f"Sua carteira está {pct(p.day_change_pct)} hoje e {pct(p.result_pct)} sobre o preço médio.")
    quoted = [q for q in (market.quotes if market else []) if q.change_pct is not None]
    if len(quoted) >= 2:
        best = max(quoted, key=lambda q: q.change_pct)
        worst = min(quoted, key=lambda q: q.change_pct)
        parts.append(f"Maior alta: {best.ticker}, {pct(best.change_pct)}. Maior queda: {worst.ticker}, {pct(worst.change_pct)}.")
    return " ".join(parts) or "Ainda não tenho cotações da sua carteira."


def demo_reply(message: str, snap: Snapshot, now: datetime, assistant_name: str, address: str = "") -> str:
    """`address` é como o assistente chama você (USER_NAME): um nome ou "senhor"."""
    topic = _topic(message)
    to_you = f", {address}" if address else ""

    if topic == "advice":
        return (
            f"Receio que isso não seja comigo{to_you}: não faço recomendações de compra ou venda. "
            "Posso descrever como está a sua carteira, se desejar."
        )

    if topic == "deliverables" and snap.deliverables is not None:
        pending = [d for d in snap.deliverables if d.open and d.hours_left > 0][:3]
        if not pending:
            return "Você não tem entregas pendentes."
        items = "; ".join(f"{d.title}, de {d.course}, em {duration(d.hours_left)}" for d in pending)
        return f"Suas próximas entregas são: {items}."

    if topic == "emails" and snap.emails is not None:
        unread = [e for e in snap.emails if e.unread]
        if not unread:
            return "Nenhum e-mail não lido."
        senders = ", ".join(e.sender_name for e in unread[:3])
        return f"Você tem {plural(len(unread), 'e-mail não lido', 'e-mails não lidos')}. Os mais recentes são de {senders}."

    if topic == "calendar" and snap.events is not None:
        upcoming = [ev for ev in snap.events if ev.end > now][:3]
        if not upcoming:
            return "Sua agenda está livre nos próximos dias."
        items = "; ".join(f"{ev.title}, {_event_when(ev, now)}" for ev in upcoming)
        return f"Seus próximos compromissos: {items}."

    if topic == "portfolio" and (snap.portfolio is not None or snap.market is not None):
        return _market_reply(snap)

    if topic == "greeting":
        return (
            f"Olá{to_you}. {assistant_name} à sua disposição, em modo demonstração. "
            "Pergunte sobre entregas, e-mails, agenda ou carteira."
        )

    return (
        f"Receio que, em modo demonstração, eu entenda apenas alguns assuntos{to_you}: "
        "entregas, e-mails, agenda e carteira. Na Fase 4 passo a responder perguntas livres."
    )
