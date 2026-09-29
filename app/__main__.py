"""Inicia o servidor local: `python -m app` (ou `python -m app --reload`).

Antes de subir, mostra no terminal o que falta configurar. É aqui, e não na
interface, que aparecem nomes de arquivos e de variáveis: o navegador só
recebe mensagens genéricas.
"""

import argparse

import uvicorn

from app.config import HOST, PORTFOLIO_FILE, Settings, get_settings, secret
from app.private import key_problem, MIN_KEY_LENGTH


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
    if key_problem(secret(settings.portfolio_access_key)):
        hints.append(f"Minha carteira: defina PORTFOLIO_ACCESS_KEY no .env, com {MIN_KEY_LENGTH} caracteres ou mais.")
    return hints


def main() -> None:
    parser = argparse.ArgumentParser(description="Inicia o servidor local do assistente.")
    parser.add_argument("--reload", action="store_true", help="reinicia sozinho ao salvar arquivos (desenvolvimento)")
    args = parser.parse_args()

    settings = get_settings()
    print(f"{settings.assistant_name} em http://{HOST}:{settings.port}")
    for hint in setup_hints(settings):
        print(f"  ! {hint}")
    uvicorn.run("app.main:app", host=HOST, port=settings.port, reload=args.reload)


if __name__ == "__main__":
    main()
