"""Conector do Canvas com a API e o feed iCal simulados (nenhuma chamada real)."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.cache import Cache
from app.connectors import canvas
from app.connectors.http import ConnectorError, read_only_client
from tests.conftest import make_settings

BASE = "https://puc-campinas.instructure.com"
TOKEN = "token-secreto-123"
ICS_URL = "https://puc-campinas.instructure.com/feeds/calendars/user_segredo.ics"
NOW = datetime.now(timezone.utc)


def iso(delta: timedelta) -> str:
    return (NOW + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def planner_item(pid, kind="assignment", due=timedelta(days=1), course_id=1, **extra) -> dict:
    item = {
        "plannable_id": pid,
        "plannable_type": kind,
        "course_id": course_id,
        "plannable_date": iso(due),
        "plannable": {"title": f"Tarefa {pid}", "due_at": iso(due)},
        "html_url": f"/courses/{course_id}/assignments/{pid}",
        "submissions": {"submitted": False, "excused": False, "graded": False, "missing": False},
    }
    item.update(extra)
    return item


def ics_calendar(*events: str) -> str:
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Canvas//EN\r\n" + "".join(events) + "END:VCALENDAR\r\n"


def ics_event(uid: str, summary: str, dtstart: str) -> str:
    return f"BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{summary}\r\n{dtstart}\r\nDTSTAMP:20260101T000000Z\r\nEND:VEVENT\r\n"


class FakeCanvas:
    """Simula o Canvas. `api_status` força um erro na API."""

    def __init__(self, pages=None, courses=None, ics=None, api_status=200, ics_status=200):
        self.pages = pages or [[]]
        self.courses = courses if courses is not None else [{"id": 1, "name": "Banco de Dados"}]
        self.ics = ics
        self.api_status = api_status
        self.ics_status = ics_status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith(".ics"):
            return httpx.Response(self.ics_status, text=self.ics or "")
        if self.api_status != 200:
            return httpx.Response(self.api_status, json={"errors": [{"message": "Invalid access token."}]})
        if path == "/api/v1/courses":
            return httpx.Response(200, json=self.courses)
        if path == "/api/v1/planner/items":
            page = int(request.url.params.get("page", "1"))
            headers = {}
            if page < len(self.pages):
                headers["Link"] = f'<{BASE}/api/v1/planner/items?page={page + 1}&per_page=100>; rel="next"'
            return httpx.Response(200, json=self.pages[page - 1], headers=headers)
        return httpx.Response(404)

    def count(self, path_part: str) -> int:
        return sum(path_part in r.url.path for r in self.requests)


@pytest.fixture
def cache(tmp_path):
    return Cache(tmp_path / "cache.sqlite3")


def run(fake, cache, force=False, **settings):
    settings.setdefault("canvas_token", TOKEN)
    s = make_settings(demo_mode=False, canvas_base_url=BASE, timezone="America/Sao_Paulo", **settings)
    http = read_only_client(transport=httpx.MockTransport(fake))
    return canvas.load(s, cache, http, force=force)


def test_not_configured_without_token_or_feed(cache):
    res = run(FakeCanvas(), cache, canvas_token=None)
    assert res.status == "not_configured"
    assert "CANVAS_TOKEN" in res.message


def test_api_statuses_courses_and_order(cache):
    fake = FakeCanvas(pages=[[
        planner_item(1, due=timedelta(days=3)),
        planner_item(2, due=timedelta(hours=10), submissions={"submitted": True}),
        planner_item(3, kind="quiz", due=timedelta(days=1)),
        planner_item(4, kind="announcement"),
        planner_item(5, kind="calendar_event"),
    ]])
    res = run(fake, cache)

    assert res.status == "ok" and res.source == "live" and res.message is None
    assert [d.id for d in res.data] == ["assignment-2", "quiz-3", "assignment-1"]  # por prazo
    by_id = {d.id: d for d in res.data}
    assert by_id["assignment-2"].status == "submitted"
    assert by_id["assignment-1"].status == "pending"
    assert by_id["quiz-3"].course == "Banco de Dados"
    assert by_id["assignment-1"].url == f"{BASE}/courses/1/assignments/1"
    assert fake.requests[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_time_window(cache):
    fake = FakeCanvas(pages=[[
        planner_item(1, due=timedelta(days=-1)),  # atrasada e pendente: aparece
        planner_item(2, due=timedelta(days=-1), submissions={"submitted": True}),  # já entregue: some
        planner_item(3, due=timedelta(days=-5)),  # atrasada há muito: some
        planner_item(4, due=timedelta(days=9)),  # além de 7 dias: some
    ]])
    assert [d.id for d in run(fake, cache).data] == ["assignment-1"]


def test_follows_pagination_link(cache):
    fake = FakeCanvas(pages=[[planner_item(1)], [planner_item(2, due=timedelta(days=2))]])
    res = run(fake, cache)
    assert [d.id for d in res.data] == ["assignment-1", "assignment-2"]
    assert fake.count("/planner/items") == 2


def test_never_sends_token_to_other_domain(cache):
    class Evil(FakeCanvas):
        def __call__(self, request):
            response = super().__call__(request)
            if request.url.path == "/api/v1/planner/items":
                response.headers["Link"] = '<https://evil.example/steal>; rel="next"'
            return response

    fake = Evil(pages=[[planner_item(1)]])
    run(fake, cache)
    assert all(r.url.host == "puc-campinas.instructure.com" for r in fake.requests)


def test_rejected_token_falls_back_to_ics(cache):
    ics = ics_calendar(
        ics_event("event-assignment-10", "Lista 5 [EST-II]", f"DTSTART:{(NOW + timedelta(days=2)):%Y%m%dT%H%M%SZ}"),
        ics_event("event-calendar-event-7", "Aula [EST-II]", f"DTSTART:{(NOW + timedelta(days=1)):%Y%m%dT%H%M%SZ}"),
    )
    res = run(FakeCanvas(api_status=401, ics=ics), cache, canvas_ics_url=ICS_URL)

    assert res.status == "ok"
    assert "recusou o token" in res.message and "feed do calendário" in res.message
    assert [(d.title, d.course, d.status) for d in res.data] == [("Lista 5", "EST-II", "unknown")]


def test_ics_only_with_all_day_assignment(cache):
    day = (NOW + timedelta(days=3)).date()
    ics = ics_calendar(ics_event("event-assignment-11", "Relatório final", f"DTSTART;VALUE=DATE:{day:%Y%m%d}"))
    res = run(FakeCanvas(ics=ics), cache, canvas_token=None, canvas_ics_url=ICS_URL)

    item = res.data[0]
    assert (item.title, item.course) == ("Relatório final", "")
    assert (item.due_at.hour, item.due_at.minute) == (23, 59)  # sem horário: vale até o fim do dia
    assert "não informa" in res.message


def test_error_messages_never_leak_secrets(cache):
    res = run(FakeCanvas(api_status=401, ics_status=404), cache, canvas_ics_url=ICS_URL)
    assert res.status == "error"
    assert TOKEN not in res.message and "segredo" not in res.message
    assert "token" in res.message and "feed" in res.message


def test_uses_cache_and_force_is_rate_limited(cache):
    fake = FakeCanvas(pages=[[planner_item(1)]])
    run(fake, cache)
    second = run(fake, cache)
    forced = run(fake, cache, force=True)  # menos de 1 minuto depois: ainda usa o cache
    assert fake.count("/planner/items") == 1
    assert second.source == "cache" and forced.source == "cache"


def test_serves_stale_data_when_canvas_is_down(cache):
    run(FakeCanvas(pages=[[planner_item(1)]]), cache)
    entry = cache.get_stale(canvas.CACHE_KEY)
    cache.set(canvas.CACHE_KEY, entry.value, ttl_seconds=-1)  # vence o cache

    res = run(FakeCanvas(api_status=503), cache)
    assert res.status == "ok" and res.source == "cache"
    assert [d.id for d in res.data] == ["assignment-1"]
    assert "Mostrando os dados de" in res.message


@pytest.mark.parametrize("raw, expected", [
    ("218161 - CÁLCULO I (MAT) 0102-04-26-2s", "CÁLCULO I"),
    ("218161P - BANCOS DE DADOS RELACIONAIS (PI) - PRÁTICA (MAT) 0103-04-26-2s", "BANCOS DE DADOS RELACIONAIS - PRÁTICA"),
    ("232010 - PF-IA GENERATIVA NA PRÁTICA: PROMPTS (INT) 0101-01-26-2s", "PF-IA GENERATIVA NA PRÁTICA: PROMPTS"),
    ("Canal POLITÉCNICA", "Canal POLITÉCNICA"),  # fora do padrão: fica igual
    ("Banco de Dados", "Banco de Dados"),
])
def test_clean_course_name(raw, expected):
    assert canvas.clean_course_name(raw) == expected


def test_client_is_read_only():
    http = read_only_client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(ConnectorError, match="só faz leituras"):
        http.post("https://example.com/x")
