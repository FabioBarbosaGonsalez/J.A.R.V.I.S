"""Palavra de ativação "Olá, Jarvis": regra de ativação, abertura do painel e instalação do modelo."""

import io
import subprocess
import sys
import zipfile

import pytest

from app import wake
from tests.conftest import make_settings


def word(text, conf=1.0, start=0.0, end=0.4):
    return {"word": text, "conf": conf, "start": start, "end": end}


# --- Regra de ativação ------------------------------------------------------------

def test_greeting_followed_by_the_name_wakes():
    result = {"result": [word("[unk]"), word("olá", 0.5, 0.5, 0.9), word("jarbas", 1.0, 0.95, 1.4)]}
    assert wake.is_wake(result, 0.8)


def test_comma_pause_still_wakes():
    """ "Olá, [pausa] Jarvis": o nome chega até 2 s depois do "olá"."""
    assert wake.is_wake({"result": [word("olá", 0.7, 0.1, 0.7), word("jarbas", 0.76, 2.5, 3.4)]}, 0.6)


@pytest.mark.parametrize("words", [
    [word("jarbas", 1.0)],  # o nome sozinho ("o Jarbas é meu vizinho")
    [word("jarbas", 1.0, 0.0, 0.4), word("olá", 1.0, 0.5, 0.9)],  # ordem trocada
    [word("olá", 1.0, 0.0, 0.4), word("jarbas", 0.5, 0.45, 0.9)],  # nome com pouca confiança
    [word("olá", 0.3, 0.0, 0.4), word("jarbas", 1.0, 0.45, 0.9)],  # cumprimento com pouca confiança
    [word("olá", 1.0, 0.0, 0.4), word("jarbas", 1.0, 2.6, 3.0)],  # pausa longa demais entre os dois
    [word("olá", 1.0, 0.0, 0.4), word("jarbas", 1.0, 0.5, 0.9), word("[unk]", 0.9, 1.0, 1.4)],  # continua falando
    [word("oi", 1.0, 0.0, 0.3), word("jarbas", 1.0, 0.35, 0.8)],  # "oi" não ativa ("oi, já vou")
])
def test_does_not_wake(words):
    assert not wake.is_wake({"result": words}, 0.8)


def test_empty_result():
    assert not wake.is_wake({"text": ""}, 0.8)


@pytest.mark.parametrize("text, confusable", [
    ("oi já vou", True),
    ("olha já vai começar", True),
    ("oi já chegou carro", True),
    ("olá já árvores", False),  # é assim que o modelo livre costuma escrever "Olá, Jarvis"
    ("olá jardim", False),
    ("olá já", False),
    ("olá já vi", False),  # "Jarvis" também sai como "já vi"
])
def test_second_check(text, confusable):
    assert wake.looks_confusable(text) is confusable


# --- Laço de escuta --------------------------------------------------------------------

class FakeDetector:
    def __init__(self, hits):
        self.hits = iter(hits)

    def feed(self, block):
        return next(self.hits)


def test_listen_wakes_and_respects_cooldown():
    calls = []
    now = [0.0]

    def clock():
        return now[0]

    def blocks():
        for t in (0, 1, 5, 20, 21):
            now[0] = t
            yield b"audio"

    detector = FakeDetector([True, False, True, True, False])
    wake.listen(make_settings(), detector, blocks(), on_wake=lambda s: calls.append(now[0]) or "ok", clock=clock)

    # Ativa em 0; em 5 ainda está no intervalo de 15 s; em 20 ativa de novo
    assert calls == [0, 20]


# --- Abrir o assistente ----------------------------------------------------------------------

def test_open_assistant_when_server_is_running(monkeypatch):
    opened = []
    monkeypatch.setattr(wake, "assistant_running", lambda port: True)
    monkeypatch.setattr(wake.webbrowser, "open", opened.append)
    monkeypatch.setattr(wake, "start_server", lambda: pytest.fail("não deveria iniciar outro servidor"))

    assert wake.open_assistant(make_settings(port=8123)) == "painel aberto"
    assert opened == ["http://127.0.0.1:8123"]


def test_open_assistant_starts_the_server(monkeypatch):
    started, waited = [], []
    monkeypatch.setattr(wake, "assistant_running", lambda port: False)
    monkeypatch.setattr(wake, "start_server", lambda: started.append(True))
    monkeypatch.setattr("app.__main__.open_when_ready", lambda url, port, timeout: waited.append((url, port)))

    assert wake.open_assistant(make_settings(port=8123)) == "servidor iniciado"
    assert started == [True]
    assert waited == [("http://127.0.0.1:8123", 8123)]


def test_start_server_runs_hidden_with_a_log(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(wake, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(wake.subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))

    wake.start_server()

    [(args, kw)] = calls
    assert args[1:] == ["-m", "app"]
    assert args[0].endswith("python.exe") or args[0] == sys.executable
    assert kw["cwd"] == wake.BASE_DIR
    assert kw["stdin"] is subprocess.DEVNULL
    if sys.platform == "win32":
        assert kw["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert (tmp_path / "logs" / "servidor.log").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="trava do Windows")
def test_only_one_listener_at_a_time():
    import ctypes

    name = "Local\\JarvisEscutaTeste"
    first = wake.single_instance(name)
    try:
        assert first is not None
        assert wake.single_instance(name) is None
    finally:
        ctypes.windll.kernel32.CloseHandle(first)
    second = wake.single_instance(name)
    assert second is not None
    ctypes.windll.kernel32.CloseHandle(second)


# --- Modelo de voz -----------------------------------------------------------------------------

def zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def test_download_model(monkeypatch, tmp_path):
    target = tmp_path / "modelos" / "vosk-model-small-pt-0.3"
    data = zip_bytes({"vosk-model-small-pt-0.3/final.mdl": b"modelo", "vosk-model-small-pt-0.3/README": b"x"})
    monkeypatch.setattr(wake.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(data))

    assert wake.download_model(target) == target
    assert (target / "final.mdl").read_bytes() == b"modelo"
    # Já baixado: não baixa de novo
    monkeypatch.setattr(wake.urllib.request, "urlopen", lambda url, timeout: pytest.fail("baixou de novo"))
    wake.download_model(target)


def test_download_rejects_paths_outside_the_folder(monkeypatch, tmp_path):
    target = tmp_path / "modelos" / "vosk-model-small-pt-0.3"
    data = zip_bytes({"../fora.txt": b"x", "vosk-model-small-pt-0.3/final.mdl": b"m"})
    monkeypatch.setattr(wake.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(data))

    with pytest.raises(ValueError):
        wake.download_model(target)
    assert not (tmp_path / "modelos" / "fora.txt").exists()
    assert not target.exists()


# --- Com o modelo de verdade (só se ele já foi baixado) ------------------------------------------

@pytest.mark.skipif(not (wake.MODEL_DIR / "final.mdl").exists(), reason="modelo de voz não baixado")
def test_greeting_and_name_in_separate_results():
    """Com a pausa da vírgula, o "olá" e o nome chegam em resultados separados."""
    detector = wake.Detector(min_confidence=0.6)
    detector._transcribe = lambda audio: "olá já árvores"
    assert not detector._check({"text": "olá", "result": [word("olá", 0.9, 0.1, 0.6)]})
    assert detector._check({"text": "jarbas", "result": [word("jarbas", 0.77, 1.8, 2.5)]})
    # "Olá. O Jarbas chegou": continua falando depois do nome
    assert not detector._check({"text": "olá", "result": [word("olá", 0.9, 5.1, 5.6)]})
    assert not detector._check({"text": "jarbas [unk]", "result": [word("jarbas", 1.0, 6.0, 6.5), word("[unk]", 0.9, 6.6, 7.0)]})


@pytest.mark.skipif(not (wake.MODEL_DIR / "final.mdl").exists(), reason="modelo de voz não baixado")
def test_silence_never_wakes():
    detector = wake.Detector()
    silence = bytes(wake.BLOCK_SIZE * 2)
    assert not any(detector.feed(silence) for _ in range(20))
    assert not detector.flush()
