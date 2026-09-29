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
    "portfolio": ("carteira", "investimento", "acoes", "fii", "dividendo", "provento"),
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
        pending = [d for d in snap.deliverables if d.status == "pending" and d.hours_left > 0][:3]
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

    if topic == "portfolio" and snap.portfolio is not None:
        p = snap.portfolio
        return (
            f"A carteira soma {brl(p.total_value)}, com variação de {pct(p.day_change_pct)} hoje "
            f"e resultado de {pct(p.result_pct)} sobre o preço médio."
        )

    if topic == "greeting":
        return (
            f"Olá{to_you}. {assistant_name} à sua disposição, em modo demonstração. "
            "Pergunte sobre entregas, e-mails, agenda ou carteira."
        )

    return (
        f"Receio que, em modo demonstração, eu entenda apenas alguns assuntos{to_you}: "
        "entregas, e-mails, agenda e carteira. Na Fase 4 passo a responder perguntas livres."
    )
