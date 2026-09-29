"""Briefing do dia.

Por enquanto, o briefing é montado por regras simples que já cruzam as fontes
(prazo apertado + e-mail do professor + agenda até o prazo). Na Fase 4, o modelo
de IA passa a redigir o texto, e esta versão por regras continua como plano B
para quando a cota da API acabar ou houver erro.
"""

from datetime import datetime

from app.formatting import brl, duration, normalize, pct, plural
from app.models import Briefing, Highlight
from app.sources import Snapshot

BUSY_DAY_THRESHOLD = 4


def _greeting(now: datetime, user_name: str) -> str:
    if 5 <= now.hour < 12:
        greeting = "Bom dia"
    elif now.hour < 18:
        greeting = "Boa tarde"
    else:
        greeting = "Boa noite"
    return f"{greeting}, {user_name}." if user_name else f"{greeting}."


def build_rule_briefing(snap: Snapshot, now: datetime, user_name: str = "") -> Briefing:
    parts: list[str] = [_greeting(now, user_name)]
    highlights: list[Highlight] = []

    # Faculdade: o que vence primeiro, cruzado com e-mails e agenda
    if snap.deliverables is not None:
        pending = [d for d in snap.deliverables if d.status == "pending" and d.hours_left > 0]
        urgent = [d for d in pending if d.urgent]
        if urgent:
            first = urgent[0]
            parts.append(f"Atenção: {first.title}, de {first.course}, vence em {duration(first.hours_left)}.")
            highlights.append(Highlight(level="critical", text=f"{first.course}: prazo em {duration(first.hours_left)}"))

            course_key = normalize(first.course)
            related = [
                e for e in (snap.emails or [])
                if e.unread and e.from_university and course_key in normalize(e.subject)
            ]
            if related:
                parts.append(f"Há um e-mail não lido de {related[0].sender_name} sobre essa disciplina.")

            if snap.events is not None:
                before_due = [
                    ev for ev in snap.events
                    if not ev.all_day and now < ev.start < first.due_at
                ]
                if before_due:
                    parts.append(
                        f"Até o prazo você ainda tem {plural(len(before_due), 'compromisso', 'compromissos')} na agenda, "
                        "então reserve um horário para terminar."
                    )
        elif pending:
            first = pending[0]
            parts.append(f"A próxima entrega é {first.title}, de {first.course}, em {duration(first.hours_left)}.")
        else:
            parts.append("Nenhuma entrega pendente na faculdade.")

    # E-mails
    if snap.emails is not None:
        unread = [e for e in snap.emails if e.unread]
        from_uni = [e for e in unread if e.from_university]
        if unread:
            text = f"Você tem {plural(len(unread), 'e-mail não lido', 'e-mails não lidos')}"
            if from_uni:
                text += f", {len(from_uni)} da faculdade"
            parts.append(text + ".")
            if from_uni:
                highlights.append(Highlight(level="warning", text=f"{len(from_uni)} e-mail(s) da faculdade não lido(s)"))
        else:
            parts.append("Sua caixa de entrada está em dia.")

    # Agenda de hoje
    if snap.events is not None:
        today = [ev for ev in snap.events if ev.start.date() == now.date() and not ev.all_day]
        remaining = [ev for ev in today if ev.end > now]
        if remaining:
            nxt = remaining[0]
            parts.append(
                f"Hoje ainda restam {plural(len(remaining), 'compromisso', 'compromissos')}; "
                f"o próximo é {nxt.title}, às {nxt.start:%H:%M}."
            )
        else:
            parts.append("Não há mais compromissos na agenda de hoje.")
        if len(today) >= BUSY_DAY_THRESHOLD:
            highlights.append(Highlight(level="warning", text=f"Dia lotado: {len(today)} compromissos"))

    # Carteira: só descreve, nunca recomenda
    if snap.portfolio is not None and snap.portfolio.positions:
        p = snap.portfolio
        parts.append(f"A carteira soma {brl(p.total_value)}, {pct(p.day_change_pct)} no dia.")
        highlights.append(Highlight(level="info", text=f"Carteira {pct(p.day_change_pct)} hoje"))

    unavailable = [
        name for name, value in (
            ("e-mails", snap.emails), ("agenda", snap.events),
            ("faculdade", snap.deliverables), ("carteira", snap.portfolio),
        ) if value is None
    ]
    if unavailable:
        parts.append(f"Sem dados de: {', '.join(unavailable)}.")

    return Briefing(text=" ".join(parts), highlights=highlights, generated_at=now, generator="rules")
