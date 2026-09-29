"""Aplicação FastAPI: rotas da API e arquivos estáticos da interface."""

import mimetypes
from datetime import datetime
from typing import Annotated, Callable, Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__, private, sources
from app.config import STATIC_DIR, Settings, get_settings, secret
from app.llm.briefing import build_rule_briefing
from app.llm.chat import demo_reply
from app.models import (
    Briefing,
    CalendarEvent,
    ChatRequest,
    ChatResponse,
    Deliverable,
    Email,
    GoogleStatusResponse,
    Market,
    PanelResponse,
    Portfolio,
    PrivateStatus,
    StatusResponse,
    UnlockRequest,
)

# No Windows, o registro às vezes associa .js a "text/plain", e o navegador
# se recusa a carregar <script type="module">. Fixamos os tipos aqui.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

LOCAL_HOSTNAMES = {"127.0.0.1", "localhost"}

app = FastAPI(
    title="Assistente pessoal",
    version=__version__,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

# Recusa requisições cujo header Host não seja local. Protege contra
# "DNS rebinding": um site malicioso apontando um domínio para 127.0.0.1
# para ler seus e-mails pelo navegador.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(LOCAL_HOSTNAMES))


@app.middleware("http")
async def local_only_guards(request: Request, call_next):
    # Outros sites não podem disparar ações (ex.: chat, que gasta cota da IA).
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin is not None and urlparse(origin).hostname not in LOCAL_HOSTNAMES:
            return JSONResponse({"detail": "Origem não permitida."}, status_code=403)

    response = await call_next(request)

    # Sempre revalidar a interface, para você não ver JS/CSS antigos após atualizar o código.
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


SettingsDep = Annotated[Settings, Depends(get_settings)]
Simulate = Annotated[
    Literal["error", "not_configured"] | None,
    Query(description="Somente no modo demo: força um estado do painel para testar a interface."),
]


def _panel(load: Callable[[Settings], PanelResponse], settings: Settings, simulate: str | None) -> PanelResponse:
    if simulate and settings.demo_mode:
        now = datetime.now(settings.tz)
        if simulate == "error":
            return PanelResponse(status="error", updated_at=now, message="Falha simulada (modo demonstração).")
        return PanelResponse(status="not_configured", updated_at=now, message="Fonte não configurada (simulação).")
    return load(settings)


# --- Interface ------------------------------------------------------------

@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --- API ------------------------------------------------------------------

@app.get("/api/status", response_model=StatusResponse)
def get_status(settings: SettingsDep):
    return StatusResponse(
        assistant_name=settings.assistant_name,
        user_name=settings.user_name,
        demo_mode=settings.demo_mode,
        refresh_seconds=settings.refresh_seconds,
        version=__version__,
    )


Force = Annotated[bool, Query(description="Ignora o cache (com um intervalo mínimo entre buscas).")]


@app.get("/api/emails", response_model=PanelResponse[list[Email]])
def get_emails(settings: SettingsDep, simulate: Simulate = None, force: Force = False):
    return _panel(lambda s: sources.emails_panel(s, force=force), settings, simulate)


@app.get("/api/calendar", response_model=PanelResponse[list[CalendarEvent]])
def get_calendar(settings: SettingsDep, simulate: Simulate = None, force: Force = False):
    return _panel(lambda s: sources.calendar_panel(s, force=force), settings, simulate)


# --- Conexão com o Google (Gmail e Agenda) --------------------------------------

@app.get("/api/google/status", response_model=GoogleStatusResponse)
def google_status(settings: SettingsDep):
    if settings.demo_mode:
        return GoogleStatusResponse(state="demo")
    status = sources.get_google_auth(settings).status()
    return GoogleStatusResponse(state=status.state, message=status.message)


@app.post("/api/google/connect", response_model=GoogleStatusResponse)
def google_connect(settings: SettingsDep):
    """Abre o consentimento do Google no navegador desta máquina (só leitura)."""
    if settings.demo_mode:
        return GoogleStatusResponse(state="demo")
    status = sources.get_google_auth(settings).start_connect()
    return GoogleStatusResponse(state=status.state, message=status.message)


@app.get("/api/canvas", response_model=PanelResponse[list[Deliverable]])
def get_canvas(settings: SettingsDep, simulate: Simulate = None, force: Force = False):
    return _panel(lambda s: sources.canvas_panel(s, force=force), settings, simulate)


@app.get("/api/market", response_model=PanelResponse[Market])
def get_market(settings: SettingsDep, simulate: Simulate = None):
    """Painel da home: dólar ao vivo e cotações da carteira, sem valores investidos."""
    return _panel(sources.market_panel, settings, simulate)


# --- Aba privada "Minha carteira" ---------------------------------------------
# A carteira completa só sai de /api/private/portfolio, com a sessão desbloqueada.

NO_STORE = {"Cache-Control": "no-store"}  # nada da aba privada fica no cache do navegador


def _access_key(settings: Settings) -> str:
    """A chave configurada, ou "" se faltar ou for curta demais (aba desativada)."""
    key = secret(settings.portfolio_access_key)
    return "" if private.key_problem(key) else key


def _session_ok(request: Request, settings: Settings) -> bool:
    token = request.cookies.get(private.COOKIE_NAME)
    return private.sessions.check(token, settings.private_session_minutes * 60)


@app.get("/api/private/status", response_model=PrivateStatus)
def private_status(request: Request, settings: SettingsDep, response: Response):
    response.headers.update(NO_STORE)
    problem = private.key_problem(secret(settings.portfolio_access_key))
    return PrivateStatus(
        enabled=problem is None,
        unlocked=problem is None and _session_ok(request, settings),
        session_minutes=settings.private_session_minutes,
        message=problem,
    )


@app.post("/api/private/unlock")
def private_unlock(body: UnlockRequest, settings: SettingsDep):
    key = _access_key(settings)
    if not key:
        problem = private.key_problem(secret(settings.portfolio_access_key))
        return JSONResponse({"detail": problem}, 403, headers=NO_STORE)

    result = private.sessions.unlock(body.key, key)
    if not result.ok:
        if result.retry_after:
            return JSONResponse(
                {"detail": f"Muitas tentativas. Aguarde {result.retry_after} s.", "retry_after": result.retry_after},
                429, headers={**NO_STORE, "Retry-After": str(result.retry_after)})
        return JSONResponse({"detail": "Chave incorreta."}, 401, headers=NO_STORE)

    response = JSONResponse({"unlocked": True}, headers=NO_STORE)
    response.set_cookie(
        private.COOKIE_NAME, result.token, path=private.COOKIE_PATH,
        httponly=True, samesite="strict", max_age=settings.private_session_minutes * 60,
    )
    return response


@app.post("/api/private/lock")
def private_lock(request: Request):
    private.sessions.lock(request.cookies.get(private.COOKIE_NAME))
    response = JSONResponse({"unlocked": False}, headers=NO_STORE)
    response.delete_cookie(private.COOKIE_NAME, path=private.COOKIE_PATH)
    return response


@app.get("/api/private/portfolio", response_model=PanelResponse[Portfolio])
def private_portfolio(request: Request, settings: SettingsDep, response: Response):
    response.headers.update(NO_STORE)
    if not _access_key(settings):
        return JSONResponse({"detail": "Aba privada desativada."}, 403, headers=NO_STORE)
    if not _session_ok(request, settings):
        return JSONResponse({"detail": "Aba bloqueada."}, 401, headers=NO_STORE)
    return sources.portfolio_panel(settings)


@app.get("/api/briefing", response_model=PanelResponse[Briefing])
def get_briefing(settings: SettingsDep, simulate: Simulate = None):
    def load(s: Settings) -> PanelResponse[Briefing]:
        now = datetime.now(s.tz)
        briefing = build_rule_briefing(sources.snapshot(s), now, s.user_name)
        return PanelResponse(status="ok", source="demo" if s.demo_mode else "live", updated_at=now, data=briefing)

    return _panel(load, settings, simulate)


@app.post("/api/chat", response_model=ChatResponse)
def post_chat(body: ChatRequest, settings: SettingsDep):
    now = datetime.now(settings.tz)
    reply = demo_reply(body.message, sources.snapshot(settings), now, settings.assistant_name, settings.user_name)
    return ChatResponse(reply=reply, generator="demo")
