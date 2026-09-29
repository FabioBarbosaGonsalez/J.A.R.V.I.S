from datetime import datetime, timedelta, timezone

from app.formatting import brl, duration, pct
from app.llm.chat import _topic
from app.models import Deliverable, Portfolio, Position


def test_position_math():
    p = Position(ticker="XPTO3", asset_type="ação", quantity=10, avg_price=20, price=25, day_change_pct=25)
    assert p.market_value == 250
    assert p.cost == 200
    assert p.result_value == 50
    assert p.result_pct == 25
    assert p.day_change_value == 50  # ontem valia 200


def test_portfolio_totals_and_allocation():
    pf = Portfolio(positions=[
        Position(ticker="A", asset_type="ação", quantity=10, avg_price=10, price=10, day_change_pct=0),
        Position(ticker="B", asset_type="FII", quantity=30, avg_price=10, price=10, day_change_pct=0),
    ])
    assert pf.total_value == 400
    assert pf.result_value == 0
    assert [(a.asset_type, a.pct) for a in pf.allocation] == [("FII", 75.0), ("ação", 25.0)]


def test_empty_portfolio_does_not_divide_by_zero():
    pf = Portfolio(positions=[])
    assert pf.total_value == 0
    assert pf.result_pct == 0
    assert pf.day_change_pct == 0
    assert pf.allocation == []


def test_deliverable_urgency():
    now = datetime.now(timezone.utc)
    soon = Deliverable(id="1", title="t", course="c", due_at=now + timedelta(hours=10), status="pending")
    later = Deliverable(id="2", title="t", course="c", due_at=now + timedelta(days=3), status="pending")
    late = Deliverable(id="3", title="t", course="c", due_at=now - timedelta(hours=1), status="pending")
    assert soon.urgent and not later.urgent and not late.urgent


def test_formatting():
    assert brl(1234.5) == "R$ 1.234,50"
    assert brl(-3) == "-R$ 3,00"
    assert pct(0.654) == "+0,65%"
    assert duration(30) == "1 dia e 6 horas"
    assert duration(5.4) == "5 horas"
    assert duration(48) == "2 dias"


def test_chat_topics_match_whole_words():
    assert _topic("como está a carteira hoje?") == "portfolio"
    assert _topic("tenho e-mails novos?") == "emails"
    assert _topic("o que faço depois?") is None  # "oi" dentro de "depois" não é saudação
