"""Camada de abstração do modelo de IA.

O resto do app só conhece os tipos deste arquivo (`Tool`, `Turn`, `Reply`) e o
protocolo `LLMProvider`. Para trocar de provedor (Groq, Ollama local...), basta
escrever outra classe com o mesmo método `run` e escolhê-la em `get_provider`.

O laço de ferramentas fica dentro do provedor: cada API tem o próprio formato
de chamada e de resposta de ferramenta (e o Gemini exige devolver as
"assinaturas de pensamento" do modelo sem mexer nelas).
"""

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal, Protocol

from app.config import Settings, secret

log = logging.getLogger(__name__)

# Limite de tamanho da resposta do modelo: o assistente fala frases curtas,
# e isso economiza a cota gratuita.
MAX_OUTPUT_TOKENS = 1024
REQUEST_TIMEOUT_MS = 20_000


@dataclass(frozen=True)
class Tool:
    """Ferramenta que o modelo pode pedir para chamar. `parameters` é um JSON Schema."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})


@dataclass(frozen=True)
class Turn:
    """Uma fala anterior da conversa, só em texto."""

    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class Reply:
    text: str
    model: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Quantas requisições à API a resposta gastou (para o contador de cota)
    requests: int = 0


# Recebe o nome e os argumentos da ferramenta e devolve um resultado curto em
# dicionário, que vai de volta para o modelo.
ToolExecutor = Callable[[str, dict[str, Any]], dict[str, Any]]


class LLMError(Exception):
    """A IA não conseguiu responder (erro de rede, da API ou resposta vazia)."""


class QuotaExceeded(LLMError):
    """A cota gratuita acabou (por minuto ou por dia), em todos os modelos tentados."""


class LLMProvider(Protocol):
    name: str

    def run(
        self,
        *,
        system: str,
        history: Sequence[Turn],
        tools: Sequence[Tool],
        execute: ToolExecutor,
        max_tool_rounds: int = 2,
    ) -> Reply:
        """Responde à última fala de `history`, chamando ferramentas se precisar.

        Depois de `max_tool_rounds` rodadas de ferramentas, o modelo é obrigado
        a responder só com texto: cada rodada é uma requisição a mais na cota.
        """
        ...


def _run_tool(execute: ToolExecutor, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Executa a ferramenta sem derrubar a conversa: um erro vira uma resposta para o modelo."""
    try:
        return execute(name, args)
    except Exception as exc:  # noqa: BLE001 - o modelo precisa saber que falhou
        log.warning("Ferramenta %s falhou: %s", name, type(exc).__name__)
        return {"erro": "Não foi possível obter esses dados agora."}


class GeminiProvider:
    """Google Gemini pelo SDK oficial `google-genai`.

    Usa `models.generate_content`, que não guarda estado no Google: o histórico
    vive aqui e é reenviado a cada requisição. Se a cota do modelo principal
    acabar, tenta de novo com o modelo reserva.
    """

    name = "gemini"

    def __init__(self, api_key: str, model: str, fallback_model: str = "", client: Any = None):
        if client is None:
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    timeout=REQUEST_TIMEOUT_MS,
                    # Sem novas tentativas automáticas: cada uma gastaria cota
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        self._client = client
        self.models = [m for m in (model, fallback_model) if m]
        # Tira repetição se o reserva for igual ao principal
        self.models = list(dict.fromkeys(self.models))

    def __repr__(self) -> str:
        # Nunca mostra a chave
        return f"GeminiProvider(models={self.models!r})"

    def run(
        self,
        *,
        system: str,
        history: Sequence[Turn],
        tools: Sequence[Tool],
        execute: ToolExecutor,
        max_tool_rounds: int = 2,
    ) -> Reply:
        from google.genai import errors

        # Requisições que passaram, somando as tentativas em todos os modelos
        usage = {"requests": 0}
        quota_only = True  # todos os modelos falharam por cota?
        for model in self.models:
            try:
                reply = self._run_with(model, system, history, tools, execute, max_tool_rounds, usage)
                reply.requests = usage["requests"]
                return reply
            except errors.ClientError as exc:
                if exc.code != 429:
                    raise LLMError(f"A API do Gemini recusou o pedido ({exc.code}).") from exc
                log.warning("Cota esgotada no modelo %s", model)
            except errors.ServerError as exc:
                # 503: modelo sobrecarregado agora. O próximo modelo pode estar livre.
                if exc.code != 503:
                    raise LLMError(f"A API do Gemini falhou ({exc.code}).") from exc
                log.warning("Modelo %s sobrecarregado", model)
                quota_only = False
            except errors.APIError as exc:
                raise LLMError(f"A API do Gemini falhou ({exc.code}).") from exc
            except LLMError:
                raise
            except Exception as exc:  # rede, timeout
                raise LLMError("Não foi possível falar com a API do Gemini.") from exc
        if quota_only:
            raise QuotaExceeded("A cota gratuita do Gemini acabou por enquanto.")
        raise LLMError("O Gemini está sobrecarregado agora. Tente de novo em instantes.")

    def _run_with(
        self,
        model: str,
        system: str,
        history: Sequence[Turn],
        tools: Sequence[Tool],
        execute: ToolExecutor,
        max_tool_rounds: int,
        usage: dict[str, int],
    ) -> Reply:
        from google.genai import types

        contents = [
            types.Content(role="user" if t.role == "user" else "model", parts=[types.Part(text=t.text)])
            for t in history
        ]
        declarations = [
            types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters)
            for t in tools
        ]
        calls: list[ToolCall] = []

        for round_ in range(max_tool_rounds + 1):
            last_round = round_ == max_tool_rounds
            config = types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                # O laço é nosso: o SDK não executa nada sozinho
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
            if declarations:
                config.tools = [types.Tool(function_declarations=declarations)]
                if last_round:
                    config.tool_config = types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.NONE)
                    )

            response = self._client.models.generate_content(model=model, contents=contents, config=config)
            usage["requests"] += 1

            candidate = (response.candidates or [None])[0]
            content = candidate.content if candidate else None
            parts = (content.parts if content else None) or []
            function_calls = [p.function_call for p in parts if p.function_call]

            if not function_calls:
                text = "".join(p.text for p in parts if p.text and not p.thought).strip()
                if not text:
                    raise LLMError("O Gemini devolveu uma resposta vazia.")
                return Reply(text=text, model=model, tool_calls=calls)

            # Devolve o turno do modelo exatamente como veio (com as assinaturas de pensamento)
            contents.append(content)
            results = []
            for fc in function_calls:
                args = dict(fc.args or {})
                calls.append(ToolCall(name=fc.name, args=args))
                result = _run_tool(execute, fc.name, args)
                results.append(types.Part(function_response=types.FunctionResponse(
                    id=fc.id, name=fc.name, response=result,
                )))
            contents.append(types.Content(role="user", parts=results))

        # Não chega aqui: a última rodada proíbe ferramentas
        raise LLMError("O Gemini insistiu em chamar ferramentas.")


@lru_cache(maxsize=4)
def _gemini(api_key: str, model: str, fallback_model: str) -> GeminiProvider:
    # Um cliente por configuração: reaproveita as conexões HTTP entre perguntas
    return GeminiProvider(api_key, model, fallback_model)


def get_provider(settings: Settings) -> LLMProvider | None:
    """Provedor configurado no `.env`, ou None se a IA não estiver configurada."""
    if settings.llm_provider == "gemini":
        api_key = secret(settings.gemini_api_key)
        if not api_key or not settings.gemini_model:
            return None
        return _gemini(api_key, settings.gemini_model, settings.gemini_fallback_model)
    return None


def tool_result(data: Any) -> dict[str, Any]:
    """Empacota o resultado de uma ferramenta: o Gemini exige um objeto JSON, não uma lista."""
    return {"resultado": json.loads(json.dumps(data, default=str, ensure_ascii=False))}
