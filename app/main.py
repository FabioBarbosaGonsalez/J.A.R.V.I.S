"""Aplicação FastAPI: rotas da API e arquivos estáticos da interface."""

import mimetypes
from datetime import datetime
from typing import Annotated, Callable, Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__, sources
from app.config import STATIC_DIR, Settings, get_settings
from app.llm.briefing import build_rule_briefing
from app.llm.chat import demo_reply
from app.models import (
    Briefing,
    CalendarEvent,
    ChatRequest,
    ChatResponse,
    Deliverable,
    Email,
    PanelResponse,
    Portfolio,
    StatusResponse,
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


@app.get("/api/emails", response_model=PanelResponse[list[Email]])
def get_emails(settings: SettingsDep, simulate: Simulate = None):
    return _panel(sources.emails_panel, settings, simulate)


@app.get("/api/calendar", response_model=PanelResponse[list[CalendarEvent]])
def get_calendar(settings: SettingsDep, simulate: Simulate = None):
    return _panel(sources.calendar_panel, settings, simulate)


@app.get("/api/canvas", response_model=PanelResponse[list[Deliverable]])
def get_canvas(settings: SettingsDep, simulate: Simulate = None):
    return _panel(sources.canvas_panel, settings, simulate)


@app.get("/api/portfolio", response_model=PanelResponse[Portfolio])
def get_portfolio(settings: SettingsDep, simulate: Simulate = None):
    return _panel(sources.portfolio_panel, settings, simulate)


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
