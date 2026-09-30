"""Camada de IA: laço de ferramentas, cota e modelo reserva, sem chamar a API real."""

import pytest
from google.genai import errors, types

from app.llm.provider import (
    GeminiProvider,
    LLMError,
    QuotaExceeded,
    Tool,
    Turn,
    get_provider,
    tool_result,
)
from tests.conftest import make_settings

EVENTS = Tool(
    name="listar_eventos",
    description="Lista os próximos eventos da agenda.",
    parameters={"type": "object", "properties": {"dias": {"type": "integer"}}},
)
HISTORY = [Turn(role="user", text="O que tenho amanhã?")]


def text_response(text: str) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model", parts=[types.Part(text=text)]),
    )])


def call_response(name: str, args: dict, call_id: str = "c1") -> types.GenerateContentResponse:
    return types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model", parts=[types.Part(
            function_call=types.FunctionCall(id=call_id, name=name, args=args),
            thought_signature=b"assinatura",
        )]),
    )])


def quota_error() -> errors.ClientError:
    return errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})


class FakeModels:
    """Devolve as respostas na ordem e guarda cada pedido recebido."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def generate_content(self, *, model, contents, config):
        # Cópia: o provedor continua mexendo na lista depois
        self.requests.append({"model": model, "contents": list(contents), "config": config})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, *responses):
        self.models = FakeModels(*responses)


def make_provider(*responses, fallback="reserva"):
    client = FakeClient(*responses)
    return GeminiProvider("chave-secreta", "principal", fallback, client=client), client.models


def no_tools(name, args):
    raise AssertionError("Nenhuma ferramenta deveria ser chamada")


def test_plain_text_answer():
    provider, models = make_provider(text_response("Amanhã está livre."))

    reply = provider.run(system="sys", history=HISTORY, tools=[EVENTS], execute=no_tools)

    assert reply.text == "Amanhã está livre."
    assert reply.model == "principal"
    assert reply.requests == 1
    assert reply.tool_calls == []
    config = models.requests[0]["config"]
    assert config.system_instruction == "sys"
    assert config.automatic_function_calling.disable is True
    assert config.tools[0].function_declarations[0].name == "listar_eventos"


def test_tool_loop_sends_result_back_with_thought_signature():
    provider, models = make_provider(
        call_response("listar_eventos", {"dias": 1}),
        text_response("Amanhã você tem Cálculo às 19h."),
    )
    seen = []

    def execute(name, args):
        seen.append((name, args))
        return tool_result([{"titulo": "Cálculo", "inicio": "19:00"}])

    reply = provider.run(system="sys", history=HISTORY, tools=[EVENTS], execute=execute)

    assert reply.text == "Amanhã você tem Cálculo às 19h."
    assert reply.requests == 2
    assert seen == [("listar_eventos", {"dias": 1})]
    assert [c.name for c in reply.tool_calls] == ["listar_eventos"]

    second = models.requests[1]["contents"]
    model_turn, tool_turn = second[-2], second[-1]
    # O turno do modelo volta intacto, com a assinatura de pensamento
    assert model_turn.parts[0].thought_signature == b"assinatura"
    response = tool_turn.parts[0].function_response
    assert (response.id, response.name) == ("c1", "listar_eventos")
    assert response.response == {"resultado": [{"titulo": "Cálculo", "inicio": "19:00"}]}


def test_last_round_forbids_more_tools():
    provider, models = make_provider(
        call_response("listar_eventos", {}),
        text_response("Pronto."),
    )

    reply = provider.run(system="s", history=HISTORY, tools=[EVENTS], execute=lambda n, a: {}, max_tool_rounds=1)

    assert reply.text == "Pronto."
    first, last = models.requests[0]["config"], models.requests[1]["config"]
    assert first.tool_config is None
    assert last.tool_config.function_calling_config.mode == types.FunctionCallingConfigMode.NONE


def test_failing_tool_becomes_error_for_the_model():
    provider, models = make_provider(call_response("listar_eventos", {}), text_response("Não consegui ver a agenda."))

    def broken(name, args):
        raise RuntimeError("token expirado: segredo")

    reply = provider.run(system="s", history=HISTORY, tools=[EVENTS], execute=broken)

    assert reply.text == "Não consegui ver a agenda."
    sent = models.requests[1]["contents"][-1].parts[0].function_response.response
    # A mensagem da exceção (que pode ter segredos) não vai para o modelo
    assert "segredo" not in str(sent)
    assert "erro" in sent


def test_quota_on_main_model_uses_fallback():
    provider, models = make_provider(quota_error(), text_response("Resposta do reserva."))

    reply = provider.run(system="s", history=HISTORY, tools=[], execute=no_tools)

    assert reply.text == "Resposta do reserva."
    assert reply.model == "reserva"
    assert [r["model"] for r in models.requests] == ["principal", "reserva"]


def test_quota_mid_loop_counts_requests_already_spent():
    provider, _ = make_provider(
        call_response("listar_eventos", {}), quota_error(),
        text_response("Ok."),
    )

    reply = provider.run(system="s", history=HISTORY, tools=[EVENTS], execute=lambda n, a: {})

    assert reply.model == "reserva"
    assert reply.requests == 2


def test_quota_on_all_models():
    provider, _ = make_provider(quota_error(), quota_error())

    with pytest.raises(QuotaExceeded):
        provider.run(system="s", history=HISTORY, tools=[], execute=no_tools)


def test_other_api_errors_do_not_try_fallback():
    bad_request = errors.ClientError(400, {"error": {"code": 400, "message": "x", "status": "INVALID_ARGUMENT"}})
    provider, models = make_provider(bad_request)

    with pytest.raises(LLMError) as info:
        provider.run(system="s", history=HISTORY, tools=[], execute=no_tools)

    assert not isinstance(info.value, QuotaExceeded)
    assert len(models.requests) == 1


def test_network_error_becomes_llm_error():
    provider, _ = make_provider(TimeoutError("lento"))

    with pytest.raises(LLMError):
        provider.run(system="s", history=HISTORY, tools=[], execute=no_tools)


def test_empty_answer_is_an_error():
    provider, _ = make_provider(text_response("   "))

    with pytest.raises(LLMError):
        provider.run(system="s", history=HISTORY, tools=[], execute=no_tools)


def test_history_roles_are_mapped():
    provider, models = make_provider(text_response("Certo."))
    history = [Turn("user", "Oi"), Turn("assistant", "Olá."), Turn("user", "E amanhã?")]

    provider.run(system="s", history=history, tools=[], execute=no_tools)

    assert [c.role for c in models.requests[0]["contents"]] == ["user", "model", "user"]
    assert models.requests[0]["config"].tools is None


def test_repr_never_shows_the_key():
    provider, _ = make_provider()
    assert "chave-secreta" not in repr(provider)


def test_same_fallback_is_not_tried_twice():
    provider = GeminiProvider("k", "principal", "principal", client=FakeClient())
    assert provider.models == ["principal"]


def test_get_provider_needs_a_key():
    assert get_provider(make_settings()) is None

    provider = get_provider(make_settings(gemini_api_key="k"))
    assert isinstance(provider, GeminiProvider)
    assert provider.models == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]


def test_tool_result_wraps_lists_and_dates():
    from datetime import date

    assert tool_result([date(2026, 9, 30)]) == {"resultado": ["2026-09-30"]}


def overloaded() -> errors.ServerError:
    return errors.ServerError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}})


def test_overloaded_model_uses_fallback():
    provider, models = make_provider(overloaded(), text_response("Resposta do reserva."))

    reply = provider.run(system="s", history=HISTORY, tools=[], execute=no_tools)

    assert reply.model == "reserva"


def test_all_models_overloaded_is_not_a_quota_problem():
    provider, _ = make_provider(overloaded(), quota_error())

    with pytest.raises(LLMError) as info:
        provider.run(system="s", history=HISTORY, tools=[], execute=no_tools)

    assert not isinstance(info.value, QuotaExceeded)
    assert "sobrecarregado" in str(info.value)
