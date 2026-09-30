"""Inicia o servidor local: `python -m app` (ou `python -m app --reload`).

Antes de subir, mostra no terminal o que falta configurar. É aqui, e não na
interface, que aparecem nomes de arquivos e de variáveis: o navegador só
recebe mensagens genéricas.

`--open` abre o painel no navegador assim que o servidor responde (é o que o
`iniciar.ps1` usa).
"""

import argparse
import errno
import json
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn
from pydantic import ValidationError

from app.config import HOST, PORTFOLIO_FILE, Settings, get_settings, secret
from app.logs import setup_logging
from app.private import MIN_KEY_LENGTH, key_problem

READY_TIMEOUT = 30  # segundos esperando o servidor antes de desistir de abrir o navegador


def setup_hints(settings: Settings) -> list[str]:
    """O que falta configurar, com o arquivo e a variável certos."""
    if settings.demo_mode:
        return ["Modo demonstração: para usar seus dados, defina DEMO_MODE=false no .env."]

    hints = []
    if not secret(settings.canvas_token) and not secret(settings.canvas_ics_url):
        hints.append("Faculdade: defina CANVAS_TOKEN ou CANVAS_ICS_URL no .env.")
    if not secret(settings.brapi_token):
        hints.append("Mercado: defina BRAPI_TOKEN no .env (token gratuito em brapi.dev).")
    if not PORTFOLIO_FILE.exists():
        hints.append("Mercado: crie data/carteira.csv a partir de data/carteira.example.csv.")
    if not settings.google_credentials_path.exists():
        hints.append(f"E-mails e Agenda: baixe a credencial OAuth (Desktop app) do Google Cloud e salve como "
                     f"{settings.google_credentials_file} na pasta do projeto (passo a passo no README).")
    elif not settings.google_token_path.exists():
        hints.append('E-mails e Agenda: clique em "Conectar Google" no painel para autorizar o acesso.')
    if key_problem(secret(settings.portfolio_access_key)):
        hints.append(f"Minha carteira: defina PORTFOLIO_ACCESS_KEY no .env, com {MIN_KEY_LENGTH} caracteres ou mais.")
    if not secret(settings.gemini_api_key):
        hints.append("IA: defina GEMINI_API_KEY no .env (chave gratuita no Google AI Studio). "
                     "Sem ela, o chat e o briefing usam só as regras básicas.")
    return hints


def _explain(error: dict) -> str:
    """Tradução dos erros de validação mais comuns; os outros ficam como o Pydantic escreve."""
    ctx = error.get("ctx") or {}
    kind = error["type"]
    if kind in ("int_parsing", "int_type", "int_from_float"):
        return "deve ser um número inteiro"
    if kind in ("float_parsing", "float_type"):
        return "deve ser um número"
    if kind in ("bool_parsing", "bool_type"):
        return "deve ser true ou false"
    if kind in ("greater_than_equal", "greater_than"):
        return f"deve ser no mínimo {ctx.get('ge', ctx.get('gt'))}"
    if kind in ("less_than_equal", "less_than"):
        return f"deve ser no máximo {ctx.get('le', ctx.get('lt'))}"
    if kind == "literal_error":
        return f"valores aceitos: {ctx.get('expected')}"
    return error["msg"]


def config_errors(exc: ValidationError) -> list[str]:
    """Erros do .env em português, sem o valor digitado (pode ser um segredo)."""
    lines = []
    for error in exc.errors():
        variable = ".".join(str(part) for part in error["loc"]).upper() or "(geral)"
        lines.append(f"{variable}: {_explain(error)}")
    return lines


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST, port))
        except OSError as exc:
            return exc.errno in (errno.EADDRINUSE, errno.EACCES, 10048, 10013)
    return False


def assistant_running(port: int) -> bool:
    """A porta ocupada é deste assistente, já aberto em outra janela?"""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/status", timeout=2) as response:
            return "assistant_name" in json.loads(response.read())
    except (OSError, ValueError):
        return False


def open_when_ready(url: str, port: int, timeout: float = READY_TIMEOUT) -> threading.Thread:
    """Abre o navegador quando o servidor começar a aceitar conexões."""

    def wait_and_open():
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((HOST, port), timeout=1):
                    webbrowser.open(url)
                    return
            except OSError:
                time.sleep(0.3)

    thread = threading.Thread(target=wait_and_open, name="abrir-navegador", daemon=True)
    thread.start()
    return thread


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inicia o servidor local do assistente.")
    parser.add_argument("--reload", action="store_true", help="reinicia sozinho ao salvar arquivos (desenvolvimento)")
    parser.add_argument("--open", action="store_true", help="abre o painel no navegador quando o servidor estiver pronto")
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
    except ValidationError as exc:
        print("Há um valor inválido no .env:", file=sys.stderr)
        for line in config_errors(exc):
            print(f"  - {line}", file=sys.stderr)
        print("Corrija o arquivo e inicie de novo (os valores aceitos estão no .env.example).", file=sys.stderr)
        return 1

    url = f"http://{HOST}:{settings.port}"
    if port_in_use(settings.port):
        if assistant_running(settings.port):
            print(f"{settings.assistant_name} já está rodando em {url}.")
            if args.open:
                webbrowser.open(url)
            return 0
        print(f"A porta {settings.port} já está em uso por outro programa.", file=sys.stderr)
        print("Feche esse programa ou escolha outra porta em PORT no .env.", file=sys.stderr)
        return 1

    setup_logging(settings)
    print(f"{settings.assistant_name} em {url}  (Ctrl+C para encerrar)")
    for hint in setup_hints(settings):
        print(f"  ! {hint}")
    if args.open:
        open_when_ready(url, settings.port)
    # log_config=None: mantém o nosso log (com o filtro de segredos) em vez do padrão do uvicorn
    uvicorn.run("app.main:app", host=HOST, port=settings.port, reload=args.reload, log_config=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
