"""Canvas (PUC-Campinas): entregas da semana.

Caminho principal: API REST com token pessoal. Usamos o endpoint do planner
(`/api/v1/planner/items`), que numa só lista traz tarefas, quizzes e fóruns
avaliados, cada um com prazo e situação da entrega. Os nomes das disciplinas
vêm de `/api/v1/courses` (guardados por 12 horas).

Plano B automático: o feed iCal do calendário, usado quando não há token ou a
API falha (algumas instituições bloqueiam tokens pessoais). O feed não informa
se a tarefa foi entregue, então essas entregas aparecem com status "unknown".
"""

import re
import threading
import time
from datetime import date, datetime, time as dtime, timedelta
from urllib.parse import urlparse

import httpx
import icalendar

from app.cache import Cache
from app.config import Settings, secret
from app.connectors.http import ConnectorError, get
from app.models import Deliverable, PanelResponse

CACHE_KEY = "canvas:deliverables"
COURSES_KEY = "canvas:courses"
TTL = 10 * 60
COURSES_TTL = 12 * 3600
# O botão "atualizar" ignora o cache, mas no máximo uma vez por minuto
MIN_FORCE_INTERVAL = 60

DAYS_AHEAD = 7
DAYS_BEHIND = 2  # atrasadas recentes continuam aparecendo
MAX_PAGES = 10
DELIVERABLE_TYPES = {"assignment", "quiz", "discussion_topic", "sub_assignment"}

API_ERRORS = {
    401: "O Canvas recusou o token (401). Ele pode ter expirado ou sido bloqueado pela instituição.",
    403: "O Canvas negou acesso com este token (403).",
}
ICS_ERRORS = {
    401: "O link do feed do calendário não é mais válido. Copie o link novamente no Canvas.",
    404: "O link do feed do calendário não foi encontrado. Copie o link novamente no Canvas.",
}

# Um painel aberto e o briefing pedem as entregas ao mesmo tempo; o lock evita
# duas buscas iguais: a segunda espera e aproveita o cache da primeira.
_lock = threading.Lock()


def load(settings: Settings, cache: Cache, http: httpx.Client, force: bool = False) -> PanelResponse[list[Deliverable]]:
    token = secret(settings.canvas_token)
    ics_url = secret(settings.canvas_ics_url)
    now = datetime.now(settings.tz)

    if not token and not ics_url:
        return PanelResponse(
            status="not_configured", source="live", updated_at=now,
            message="Defina CANVAS_TOKEN ou CANVAS_ICS_URL no arquivo .env.",
        )

    with _lock:
        cached = cache.get_stale(CACHE_KEY)
        if cached and _can_reuse(cached, force):
            return _from_cache(cached, settings)

        items, note, errors = None, None, []
        if token:
            try:
                items = _fetch_api(settings, cache, http, token, now)
            except ConnectorError as exc:
                errors.append(str(exc))
        if items is None and ics_url:
            try:
                items = _fetch_ics(http, ics_url, settings, now)
                note = "Via feed do calendário: o Canvas não informa aqui se a tarefa foi entregue."
                if errors:
                    note = f"{errors[0]} Usando o feed do calendário, sem status de entrega."
            except ConnectorError as exc:
                errors.append(str(exc))

        if items is None:
            if cached:
                stale = _from_cache(cached, settings)
                stale.message = f"{' '.join(errors)} Mostrando os dados de {stale.updated_at:%H:%M}."
                return stale
            return PanelResponse(status="error", source="live", updated_at=now, message=" ".join(errors))

        cache.set(CACHE_KEY, {
            "note": note,
            "items": [d.model_dump(mode="json", exclude={"hours_left", "urgent"}) for d in items],
        }, TTL)
        return PanelResponse(status="ok", source="live", updated_at=now, message=note, data=items)


def _can_reuse(cached, force: bool) -> bool:
    if force:
        return time.time() - cached.stored_at < MIN_FORCE_INTERVAL
    return cached.fresh


def _from_cache(entry, settings: Settings) -> PanelResponse[list[Deliverable]]:
    return PanelResponse(
        status="ok",
        source="cache",
        updated_at=datetime.fromtimestamp(entry.stored_at, settings.tz),
        message=entry.value["note"],
        data=[Deliverable(**d) for d in entry.value["items"]],
    )


def _in_window(due: datetime, status: str, now: datetime) -> bool:
    if due > now + timedelta(days=DAYS_AHEAD):
        return False
    if due >= now:
        return True
    # Prazo já passou: só interessa se sabemos que ficou pendente, e se foi há pouco
    return status == "pending" and due >= now - timedelta(days=DAYS_BEHIND)


def _sort(items: list[Deliverable]) -> list[Deliverable]:
    unique = {d.id: d for d in items}
    return sorted(unique.values(), key=lambda d: d.due_at)


# --- API REST ----------------------------------------------------------------

def _fetch_api(settings: Settings, cache: Cache, http: httpx.Client, token: str, now: datetime) -> list[Deliverable]:
    base = settings.canvas_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "start_date": (now - timedelta(days=DAYS_BEHIND)).isoformat(),
        "end_date": (now + timedelta(days=DAYS_AHEAD)).isoformat(),
        "per_page": 100,
    }
    raw = _get_all_pages(http, f"{base}/api/v1/planner/items", base, headers, params)
    courses = _course_names(http, cache, base, headers)
    items = [d for d in (_parse_planner_item(it, courses, base, settings) for it in raw) if d]
    return _sort([d for d in items if _in_window(d.due_at, d.status, now)])


def _get_all_pages(http: httpx.Client, url: str, base: str, headers: dict, params: dict | None) -> list[dict]:
    """Segue a paginação do Canvas pelo header `Link` (rel="next")."""
    results: list[dict] = []
    allowed_host = urlparse(base).netloc
    for _ in range(MAX_PAGES):
        response = get(http, url, what="o Canvas", status_messages=API_ERRORS, headers=headers, params=params)
        try:
            page = response.json()
        except ValueError:
            raise ConnectorError("O Canvas respondeu algo que não é JSON. Confira CANVAS_BASE_URL.") from None
        if not isinstance(page, list):
            raise ConnectorError("Resposta inesperada do Canvas.")
        results.extend(page)

        next_url = response.links.get("next", {}).get("url")
        # O token só vai para o próprio Canvas, nunca para outro domínio
        if not next_url or urlparse(next_url).netloc != allowed_host:
            break
        url, params = next_url, None  # a URL "next" já traz os parâmetros
    return results


def _course_names(http: httpx.Client, cache: Cache, base: str, headers: dict) -> dict[int, str]:
    cached = cache.get(COURSES_KEY)
    if cached:
        return {int(k): v for k, v in cached.value.items()}
    try:
        courses = _get_all_pages(
            http, f"{base}/api/v1/courses", base, headers, {"enrollment_state": "active", "per_page": 100},
        )
    except ConnectorError:
        return {}  # sem nomes, usamos o que o planner trouxer
    names = {c["id"]: clean_course_name(c.get("name") or c.get("course_code") or "") for c in courses if "id" in c}
    cache.set(COURSES_KEY, names, COURSES_TTL)
    return names


# Nomes da PUC-Campinas: "218161P - CÁLCULO I - PRÁTICA (MAT) 0102-04-26-2s".
# Tiramos o código da turma, as siglas entre parênteses e o código do semestre.
COURSE_NOISE = [
    re.compile(r"^\d+[A-Z]?\s+-\s+"),  # "218161P - "
    re.compile(r"\s+\d{4}-\d{2}-\d{2}-\w+$"),  # " 0102-04-26-2s"
    re.compile(r"\s*\([A-Z]{2,4}\)"),  # " (MAT)", " (PI)"
]


def clean_course_name(name: str) -> str:
    cleaned = name
    for pattern in COURSE_NOISE:
        cleaned = pattern.sub("", cleaned)
    return cleaned.strip() or name


def _parse_planner_item(item: dict, courses: dict[int, str], base: str, settings: Settings) -> Deliverable | None:
    kind = item.get("plannable_type")
    if kind not in DELIVERABLE_TYPES:
        return None
    plannable = item.get("plannable") or {}
    due_raw = plannable.get("due_at") or item.get("plannable_date")
    if not due_raw:
        return None
    try:
        due = datetime.fromisoformat(due_raw).astimezone(settings.tz)
    except ValueError:
        return None

    # `submissions` é False em itens sem entrega; senão traz submitted, excused, graded...
    subs = item.get("submissions") if isinstance(item.get("submissions"), dict) else {}
    override = item.get("planner_override") or {}
    done = subs.get("submitted") or subs.get("excused") or subs.get("graded") or override.get("marked_complete")

    return Deliverable(
        id=f"{kind}-{item.get('plannable_id')}",
        title=plannable.get("title") or plannable.get("name") or "Sem título",
        course=courses.get(item.get("course_id")) or clean_course_name(item.get("context_name") or ""),
        due_at=due,
        status="submitted" if done else "pending",
        url=_safe_url(item.get("html_url"), base),
    )


def _safe_url(url: str | None, base: str) -> str | None:
    """Só links do próprio Canvas viram links clicáveis no painel."""
    if not url:
        return None
    if url.startswith("/") and not url.startswith("//"):
        return base + url
    return url if url.startswith(base + "/") else None


# --- Feed iCal (plano B) ------------------------------------------------------

SUMMARY_RE = re.compile(r"^(?P<title>.*?)\s*\[(?P<course>[^\[\]]+)\]\s*$")


def _fetch_ics(http: httpx.Client, url: str, settings: Settings, now: datetime) -> list[Deliverable]:
    response = get(http, url, what="o feed do calendário", status_messages=ICS_ERRORS, follow_redirects=True)
    try:
        calendar = icalendar.Calendar.from_ical(response.content)
    except ValueError:
        raise ConnectorError("O link do feed do calendário não devolveu um calendário válido.") from None

    items = [d for d in (_parse_ics_event(ev, settings) for ev in calendar.walk("VEVENT")) if d]
    return _sort([d for d in items if _in_window(d.due_at, d.status, now)])


def _parse_ics_event(event, settings: Settings) -> Deliverable | None:
    # O Canvas identifica tarefas pelo UID "event-assignment-<id>";
    # eventos comuns do calendário usam "event-calendar-event-<id>" e ficam de fora.
    uid = str(event.get("UID", ""))
    if "assignment" not in uid:
        return None
    try:
        start = event.decoded("DTSTART")
    except (KeyError, ValueError):
        return None

    if isinstance(start, datetime):
        due = start if start.tzinfo else start.replace(tzinfo=settings.tz)
    elif isinstance(start, date):
        # Tarefa sem horário: vale até o fim do dia
        due = datetime.combine(start, dtime(23, 59), tzinfo=settings.tz)
    else:
        return None

    summary = str(event.get("SUMMARY", "")).strip()
    match = SUMMARY_RE.match(summary)
    title, course = (match["title"], match["course"]) if match else (summary, "")
    url = str(event.get("URL", "")) or None

    return Deliverable(
        id=uid,
        title=title or "Sem título",
        course=course,
        due_at=due.astimezone(settings.tz),
        status="unknown",
        url=url if url and url.startswith("https://") else None,
    )
