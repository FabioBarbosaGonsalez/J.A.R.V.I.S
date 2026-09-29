"""Inicia o servidor local: `python -m app` (ou `python -m app --reload`)."""

import argparse

import uvicorn

from app.config import HOST, get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Inicia o servidor local do assistente.")
    parser.add_argument("--reload", action="store_true", help="reinicia sozinho ao salvar arquivos (desenvolvimento)")
    args = parser.parse_args()

    settings = get_settings()
    print(f"{settings.assistant_name} em http://{HOST}:{settings.port}")
    uvicorn.run("app.main:app", host=HOST, port=settings.port, reload=args.reload)


if __name__ == "__main__":
    main()
