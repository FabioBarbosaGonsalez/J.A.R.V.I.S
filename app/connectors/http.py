"""Cliente HTTP compartilhado pelos conectores.

- Somente leitura por construção: qualquer método diferente de GET é recusado
  antes de sair da máquina. O token do Canvas, por exemplo, permitiria escrever
  na sua conta; este cliente garante que o painel nunca faça isso.
- A única escrita (criar evento, com a sua confirmação) usa outro cliente,
  `single_write_client`, que só aceita um método numa URL exata.
- As mensagens de erro são escritas aqui, sem a URL: as exceções do httpx
  incluem a URL, e o link do feed iCal carrega um segredo.
"""

import httpx

TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class ConnectorError(Exception):
    """Falha ao falar com uma fonte externa. A mensagem pode ser mostrada no painel."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status  # código HTTP, quando a fonte respondeu com erro


def _cap(text: str) -> str:
    """Primeira letra maiúscula, preservando o resto ("o Canvas" -> "O Canvas")."""
    return text[:1].upper() + text[1:]


def _only_get(request: httpx.Request) -> None:
    if request.method != "GET":
        raise ConnectorError(f"Bloqueado: o painel só faz leituras (tentativa de {request.method}).")


def read_only_client(**kwargs) -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT,
        headers={"User-Agent": "assistente-hud/1.0 (uso pessoal)"},
        event_hooks={"request": [_only_get]},
        **kwargs,
    )


def single_write_client(method: str, url: str, **kwargs) -> httpx.Client:
    """Cliente que só faz uma operação de escrita: `method` na URL exata `url`.

    Qualquer outra requisição (outra URL, outro método, até um GET) é recusada
    antes de sair da máquina. Ex.: só criar evento na agenda principal, nunca
    editar nem apagar.
    """
    def only_this(request: httpx.Request) -> None:
        if request.method != method or str(request.url.copy_with(query=None)) != url:
            raise ConnectorError("Bloqueado: operação de escrita não permitida.")

    return httpx.Client(
        timeout=TIMEOUT,
        headers={"User-Agent": "assistente-hud/1.0 (uso pessoal)"},
        event_hooks={"request": [only_this]},
        **kwargs,
    )


def _body_message(response: httpx.Response) -> str | None:
    try:
        message = response.json().get("message")
    except (ValueError, AttributeError):
        return None
    return message.strip()[:200] if isinstance(message, str) and message.strip() else None


def get(http: httpx.Client, url: str, **kwargs) -> httpx.Response:
    return send(http, "GET", url, **kwargs)


def send(http: httpx.Client, method: str, url: str, *, what: str, status_messages: dict[int, str] | None = None,
         use_body_message: bool = False, **kwargs) -> httpx.Response:
    """Requisição com erros traduzidos para mensagens curtas e sem segredos.

    `what` nomeia a fonte nas mensagens ("o Canvas", "a brapi").
    `status_messages` troca a mensagem padrão de códigos HTTP específicos.
    `use_body_message` usa o campo "message" do JSON de erro, quando a API
    explica o problema (ex.: limite do plano). Nunca contém a URL nem o token.
    """
    try:
        response = http.request(method, url, **kwargs)
    except ConnectorError:
        raise  # bloqueada pelo próprio cliente
    except httpx.TimeoutException:
        raise ConnectorError(f"{_cap(what)} demorou demais para responder.") from None
    except httpx.HTTPError:
        raise ConnectorError(f"Sem conexão com {what}.") from None

    code = response.status_code
    if code >= 400:
        if code in (status_messages or {}):
            message = status_messages[code]
        elif code == 429:
            message = f"Limite de requisições atingido em {what}. Tente mais tarde."
        elif use_body_message and code < 500 and (detail := _body_message(response)):
            message = f"{_cap(what)}: {detail}"
        elif code >= 500:
            message = f"{_cap(what)} está instável (erro {code})."
        else:
            message = f"{_cap(what)} recusou a requisição (erro {code})."
        raise ConnectorError(message, status=code)
    return response
