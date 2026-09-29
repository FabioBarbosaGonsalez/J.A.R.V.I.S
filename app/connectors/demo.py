"""Dados falsos para a Fase 1 (DEMO_MODE=true).

As datas são geradas em relação ao momento atual, para que prazos, "não lidas"
e compromissos de hoje sempre façam sentido quando você abre o painel.
Nomes, e-mails e valores são fictícios.
"""

from datetime import datetime, time, timedelta

from app.models import (
    AssetQuote,
    CalendarEvent,
    Deliverable,
    Dividend,
    Email,
    FxQuote,
    Market,
    Portfolio,
    Position,
)


def _now(tz) -> datetime:
    return datetime.now(tz).replace(second=0, microsecond=0)


def _at(tz, days: int, hour: int, minute: int = 0) -> datetime:
    """Data `days` dias a partir de hoje, no horário indicado."""
    day = datetime.now(tz).date() + timedelta(days=days)
    return datetime.combine(day, time(hour, minute), tzinfo=tz)


def emails(tz) -> list[Email]:
    now = _now(tz)
    return [
        Email(
            id="m1",
            sender_name="Prof. Ricardo Almeida",
            sender_email="ricardo.almeida@puc-campinas.edu.br",
            subject="Banco de Dados — dúvidas sobre a entrega do projeto",
            snippet="Pessoal, reforçando que o modelo ER precisa incluir as cardinalidades e o dicionário de dados...",
            received_at=now - timedelta(hours=3),
            unread=True,
            from_university=True,
        ),
        Email(
            id="m2",
            sender_name="Secretaria de Graduação",
            sender_email="graduacao@puc-campinas.edu.br",
            subject="Rematrícula: prazo final se aproxima",
            snippet="Lembramos que o período de rematrícula termina na próxima semana. Acesse o portal...",
            received_at=now - timedelta(hours=20),
            unread=True,
            from_university=True,
        ),
        Email(
            id="m3",
            sender_name="Ana Souza",
            sender_email="ana.souza@example.com",
            subject="Grupo de IA — reunião amanhã?",
            snippet="Oi! Consegue às 16h? Queria fechar a divisão das tarefas do trabalho de redes neurais.",
            received_at=now - timedelta(hours=5),
            unread=True,
        ),
        Email(
            id="m4",
            sender_name="RH — Empresa Exemplo",
            sender_email="rh@empresa.example",
            subject="Processo seletivo de estágio: próxima etapa",
            snippet="Parabéns! Você avançou para a entrevista técnica. Confirme o horário respondendo este e-mail.",
            received_at=now - timedelta(days=1, hours=2),
            unread=True,
        ),
        Email(
            id="m5",
            sender_name="Canvas",
            sender_email="notifications@instructure.com",
            subject="Nova nota publicada: Estatística II",
            snippet="Uma nova nota foi publicada para Lista 4 — Testes de hipótese.",
            received_at=now - timedelta(days=1, hours=6),
            unread=False,
            from_university=True,
        ),
        Email(
            id="m6",
            sender_name="Profa. Marina Costa",
            sender_email="marina.costa@puc-campinas.edu.br",
            subject="Aprendizado de Máquina: material da aula 7",
            snippet="Segue o notebook com os exemplos de validação cruzada que vimos em sala.",
            received_at=now - timedelta(days=2),
            unread=False,
            from_university=True,
        ),
        Email(
            id="m7",
            sender_name="Corretora Exemplo",
            sender_email="avisos@corretora.example",
            subject="Informe de movimentação mensal disponível",
            snippet="Seu extrato consolidado do mês já pode ser consultado na área do cliente.",
            received_at=now - timedelta(days=3),
            unread=False,
        ),
    ]


def calendar_events(tz) -> list[CalendarEvent]:
    return [
        CalendarEvent(
            id="e1",
            title="Aula — Aprendizado de Máquina",
            start=_at(tz, 0, 14),
            end=_at(tz, 0, 15, 40),
            location="Bloco H15, sala 203",
        ),
        CalendarEvent(
            id="e2",
            title="Academia",
            start=_at(tz, 0, 19),
            end=_at(tz, 0, 20),
        ),
        CalendarEvent(
            id="e3",
            title="Aula — Banco de Dados",
            start=_at(tz, 1, 8),
            end=_at(tz, 1, 11, 30),
            location="Laboratório 4",
        ),
        CalendarEvent(
            id="e4",
            title="Reunião do grupo de IA",
            start=_at(tz, 1, 16),
            end=_at(tz, 1, 17),
            location="Online",
        ),
        CalendarEvent(
            id="e5",
            title="Semana de apresentações de TCC",
            start=_at(tz, 2, 0),
            end=_at(tz, 3, 0),
            all_day=True,
        ),
        CalendarEvent(
            id="e6",
            title="Entrevista técnica — estágio",
            start=_at(tz, 3, 10),
            end=_at(tz, 3, 11),
            location="Online",
        ),
        CalendarEvent(
            id="e7",
            title="Monitoria de Estatística",
            start=_at(tz, 5, 9),
            end=_at(tz, 5, 10, 30),
            location="Bloco A, sala 12",
        ),
    ]


def deliverables(tz) -> list[Deliverable]:
    now = _now(tz)
    items = [
        Deliverable(
            id="d1",
            title="Projeto final — modelagem ER",
            course="Banco de Dados",
            due_at=now + timedelta(hours=30),
            status="pending",
        ),
        Deliverable(
            id="d2",
            title="Quiz — Redes Neurais",
            course="Aprendizado de Máquina",
            due_at=now + timedelta(hours=20),
            status="submitted",
        ),
        Deliverable(
            id="d3",
            title="Lista 5 — Regressão linear",
            course="Estatística II",
            due_at=now + timedelta(days=3, hours=4),
            status="pending",
        ),
        Deliverable(
            id="d4",
            title="Relatório de laboratório",
            course="Engenharia de Software",
            due_at=now + timedelta(days=5),
            status="pending",
        ),
        Deliverable(
            id="d5",
            title="Leitura dirigida — viés algorítmico",
            course="Ética em IA",
            due_at=now + timedelta(days=6, hours=10),
            status="pending",
        ),
    ]
    return sorted(items, key=lambda d: d.due_at)


def portfolio(tz) -> Portfolio:
    today = datetime.now(tz).date()
    positions = [
        Position(ticker="PETR4", asset_type="ação", quantity=100, avg_price=32.50, price=36.80, day_change_pct=0.9),
        Position(ticker="ITUB4", asset_type="ação", quantity=80, avg_price=28.90, price=33.10, day_change_pct=-0.4),
        Position(ticker="WEGE3", asset_type="ação", quantity=40, avg_price=38.20, price=41.50, day_change_pct=1.2),
        Position(ticker="MXRF11", asset_type="FII", quantity=300, avg_price=10.15, price=9.78, day_change_pct=0.1),
        Position(ticker="HGLG11", asset_type="FII", quantity=15, avg_price=158.40, price=162.30, day_change_pct=-0.2),
        Position(ticker="BOVA11", asset_type="ETF", quantity=30, avg_price=112.00, price=126.40, day_change_pct=0.7),
        Position(ticker="IVVB11", asset_type="ETF", quantity=10, avg_price=290.50, price=345.20, day_change_pct=0.3),
        Position(ticker="AAPL34", asset_type="BDR", quantity=25, avg_price=48.30, price=52.10, day_change_pct=-1.1),
    ]
    dividends = [
        Dividend(ticker="ITUB4", kind="Dividendo", value_per_share=0.02,
                 payment_date=today + timedelta(days=5), estimated_total=1.60),
        Dividend(ticker="MXRF11", kind="Rendimento", value_per_share=0.10,
                 payment_date=today + timedelta(days=12), estimated_total=30.00),
        Dividend(ticker="HGLG11", kind="Rendimento", value_per_share=1.10,
                 payment_date=today + timedelta(days=14), estimated_total=16.50),
        Dividend(ticker="PETR4", kind="JCP", value_per_share=0.94,
                 payment_date=today + timedelta(days=20), estimated_total=94.00),
    ]
    return Portfolio(positions=positions, dividends=dividends)


def market(tz) -> Market:
    """Painel da home: dólar e cotações, derivados da carteira de demonstração."""
    now = _now(tz)
    usd = FxQuote(pair="USD-BRL", bid=5.2072, pct_change=-0.30, high=5.2411, low=5.1976, updated_at=now)
    quotes = [
        AssetQuote(ticker=p.ticker, asset_type=p.asset_type, currency="BRL", price=p.price,
                   change_pct=p.day_change_pct, quoted_at=now)
        for p in portfolio(tz).positions
    ]
    quotes.append(AssetQuote(ticker="VOO", asset_type="ETF Internacional", currency="USD", price=540.12,
                             change_pct=0.21, quoted_at=now))
    quotes.append(AssetQuote(ticker="Tesouro Selic 2031", asset_type="Tesouro Direto",
                             note="Sem cotação ao vivo gratuita."))
    return Market(usd_brl=usd, quotes=quotes)
