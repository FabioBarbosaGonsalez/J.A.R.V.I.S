from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.llm.briefing import build_rule_briefing
from app.llm.chat import rule_reply
from app.models import CalendarEvent, Email
from app.sources import Snapshot

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 9, 29, 15, 13, tzinfo=TZ)


def event(id_: str, start_h: int, end_h: int, title: str) -> CalendarEvent:
    day = NOW.replace(minute=0)
    return CalendarEvent(id=id_, title=title, start=day.replace(hour=start_h), end=day.replace(hour=end_h))


def snap(events=None, emails=None) -> Snapshot:
    return Snapshot(emails=emails, events=events, deliverables=None, portfolio=None)


def test_ongoing_event_is_not_called_next():
    s = snap(events=[event("a", 14, 16, "Aula"), event("b", 19, 20, "Academia")])
    text = build_rule_briefing(s, NOW).text
    assert "Em andamento: Aula, até 16:00." in text
    assert "resta 1 compromisso; o próximo é Academia, às 19:00." in text
    assert "o próximo é Aula" not in text


def test_ongoing_event_and_nothing_after():
    text = build_rule_briefing(snap(events=[event("a", 14, 16, "Aula")]), NOW).text
    assert "Em andamento: Aula" in text
    assert "a agenda de hoje está livre" in text


def test_verb_agrees_with_count():
    one = build_rule_briefing(snap(events=[event("b", 19, 20, "Academia")]), NOW).text
    two = build_rule_briefing(snap(events=[event("b", 17, 18, "X"), event("c", 19, 20, "Y")]), NOW).text
    assert "Hoje ainda resta 1 compromisso" in one
    assert "Hoje ainda restam 2 compromissos" in two


def test_university_highlight_uses_real_plural():
    def mail(i: str) -> Email:
        return Email(id=i, sender_name="Prof", sender_email="p@puc-campinas.edu.br", subject="s",
                     snippet="", received_at=NOW - timedelta(hours=1), unread=True, from_university=True)

    one = build_rule_briefing(snap(emails=[mail("1")]), NOW).highlights
    two = build_rule_briefing(snap(emails=[mail("1"), mail("2")]), NOW).highlights
    assert one[0].text == "1 e-mail da faculdade não lido"
    assert two[0].text == "2 e-mails da faculdade não lidos"
    assert "(s)" not in one[0].text + two[0].text


def test_greeting_uses_configured_address():
    assert build_rule_briefing(snap(), NOW, "senhor").text.startswith("Boa tarde, senhor.")
    assert build_rule_briefing(snap(), NOW).text.startswith("Boa tarde.")


def test_chat_marks_ongoing_event():
    s = snap(events=[event("a", 14, 16, "Aula"), event("b", 19, 20, "Academia")])
    reply = rule_reply("o que tenho na agenda?", s, NOW, "J.A.R.V.I.S")
    assert "Aula, em andamento até as 16:00" in reply


def test_chat_greeting_addresses_user():
    reply = rule_reply("olá", snap(), NOW, "J.A.R.V.I.S", "senhor")
    assert reply.startswith("Olá, senhor. J.A.R.V.I.S à sua disposição")
