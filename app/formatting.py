"""Formatação em português para textos gerados no back-end (briefing e chat)."""

import unicodedata

WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")


def brl(value: float) -> str:
    """1234.5 -> 'R$ 1.234,50'"""
    text = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {text}" if value < 0 else f"R$ {text}"


def pct(value: float, signed: bool = True) -> str:
    """0.654 -> '+0,65%'"""
    text = f"{value:+.2f}" if signed else f"{value:.2f}"
    return text.replace(".", ",") + "%"


def plural(count: int, singular: str, plural_form: str) -> str:
    return f"{count} {singular if count == 1 else plural_form}"


def duration(hours: float) -> str:
    """30.0 -> '1 dia e 6 horas'; 5.4 -> '5 horas'; 0.5 -> 'menos de 1 hora'"""
    if hours < 1:
        return "menos de 1 hora"
    total = int(hours)
    days, rest = divmod(total, 24)
    if days == 0:
        return plural(rest, "hora", "horas")
    if rest == 0:
        return plural(days, "dia", "dias")
    return f"{plural(days, 'dia', 'dias')} e {plural(rest, 'hora', 'horas')}"


def normalize(text: str) -> str:
    """Minúsculas e sem acentos, para comparar palavras-chave."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))
