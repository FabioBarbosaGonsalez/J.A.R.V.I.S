"""Palavra de ativação: diga "Olá, Jarvis" e o painel abre sozinho.

Roda em segundo plano depois que você entra no Windows (o `escuta.ps1`
cuida disso) e fica esperando só essa frase:

- Reconhecimento 100% local, com o Vosk e o modelo pequeno de português
  (31 MB, Apache 2.0). O áudio não é gravado nem sai do computador.
- O reconhecedor fica limitado à frase de ativação (gramática), o que gasta
  pouco processador e evita disparar com qualquer conversa.
- "Jarvis" não existe no vocabulário do modelo; "Jarbas" existe e soa quase
  igual. Por isso a frase reconhecida é "olá jarbas", e o "Jarbas" sozinho
  nunca ativa: precisa vir depois do "olá" (até 2 s, por causa da pausa da
  vírgula) e ser a última palavra ("Olá. O Jarbas chegou" não ativa).
- Segunda checagem: quando a gramática ouve a frase, o mesmo trecho passa
  por um reconhecimento livre. Se ele ouvir "já" seguido de um verbo comum
  ("oi, já vou", "olha, já vai"), é engano e não ativa. Testado com áudios
  sintetizados: 14 de 14 "Olá, Jarvis" (com e sem pausa, com ruído moderado)
  ativaram, e nenhuma de 31 frases parecidas.
- Ao ouvir: se o servidor já está rodando, abre o painel; se não, inicia o
  servidor escondido (sem janela) e abre o painel quando ele responder.

Uso:
    python -m app.wake                 escuta (o escuta.ps1 roda assim, sem janela)
    python -m app.wake --teste         mostra no terminal o que está ouvindo, sem abrir nada
    python -m app.wake --arquivo x.wav testa um áudio gravado (16 kHz, mono)
    python -m app.wake --baixar-modelo baixa o modelo de voz, se faltar
"""

import argparse
import array
import json
import logging
import queue
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave
import webbrowser
import zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import BASE_DIR, DATA_DIR, HOST, Settings, get_settings

MODEL_NAME = "vosk-model-small-pt-0.3"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_DIR = DATA_DIR / "modelos" / MODEL_NAME
LOG_DIR = DATA_DIR / "logs"

SAMPLE_RATE = 16000
BLOCK_SIZE = 4000  # 0,25 s de áudio por bloco
GREETINGS = ("olá",)  # "oi" é curto demais: "oi, já vou" soa como "oi, Jarvis"
NAME = "jarbas"  # como o modelo escreve "Jarvis" (ver a explicação acima)
# A frase inteira e as partes soltas: com a pausa da vírgula ("Olá, [pausa] Jarvis"),
# o reconhecedor fecha a frase no "olá" e o nome chega sozinho na seguinte.
GRAMMAR = [f"{greeting} {NAME}" for greeting in GREETINGS] + list(GREETINGS) + [NAME, "[unk]"]
MAX_UTTERANCE_BYTES = SAMPLE_RATE * 2 * 10  # guarda até 10 s da fala atual para a segunda checagem
# "já" + verbo comum: a confusão típica com "Jarvis" ("oi, já vou", "olha, já vai começar")
CONFUSABLE_AFTER_JA = {
    # Sem "vi"/"viu": o reconhecimento livre costuma escrever "Jarvis" como "já vi"
    "vou", "vai", "vamos", "foi", "fui", "fiz", "fez", "está", "tá", "estou", "estava", "sei",
    "volto", "volta", "chegou", "cheguei", "chega", "era", "é", "tem", "tenho", "deu", "passou", "acabou",
    "começou", "começa", "terminou", "comi", "saiu", "falei", "disse", "sabe", "vem", "venho",
}
MAX_GAP_SECONDS = 2.0  # pausa máxima entre o "olá" e o nome (a vírgula falada chega a ~1,8 s)
COOLDOWN_SECONDS = 15  # depois de ativar, ignora repetições por um tempo
MIC_RETRY_SECONDS = 30

log = logging.getLogger("escuta")


# --- Reconhecimento ------------------------------------------------------------------

def volume_percent(audio: bytes) -> int:
    """Pico do áudio em % do máximo. Fala perto do microfone costuma passar de 10%."""
    samples = array.array("h", audio[: len(audio) // 2 * 2])
    return round(max(map(abs, samples), default=0) / 327.67)


def looks_confusable(free_text: str) -> bool:
    """O reconhecimento livre ouviu "já" + verbo comum? Então não era "Jarvis"."""
    words = free_text.split()
    return any(a == "já" and b in CONFUSABLE_AFTER_JA for a, b in zip(words, words[1:]))


def is_wake(result: dict, min_confidence: float) -> bool:
    """As palavras terminam em "olá" seguido do nome, com uma pausa curta entre os dois?

    O nome precisa ser a última palavra: quem chama o assistente para depois
    do nome; "Olá. O Jarbas chegou" e "Olá. Já vou sair" continuam falando.
    """
    words = result.get("result") or []
    if len(words) < 2:
        return False
    first, second = words[-2], words[-1]
    return (
        first["word"] in GREETINGS
        and second["word"] == NAME
        and second["conf"] >= min_confidence
        and first["conf"] >= min_confidence / 2  # "olá" é curto e costuma vir com confiança menor
        and second["start"] - first["end"] <= MAX_GAP_SECONDS
    )


class Detector:
    """Recebe blocos de áudio (16 kHz, mono, 16 bits) e diz quando ouviu a frase."""

    def __init__(self, model_dir: Path = MODEL_DIR, min_confidence: float = 0.6):
        import vosk

        vosk.SetLogLevel(-1)
        self._vosk = vosk
        self.min_confidence = min_confidence
        self._model = vosk.Model(str(model_dir))
        self._recognizer = vosk.KaldiRecognizer(self._model, SAMPLE_RATE, json.dumps(GRAMMAR, ensure_ascii=False))
        self._recognizer.SetWords(True)
        self._utterance = bytearray()  # áudio da fala atual, para a segunda checagem
        # "olá" que terminou a frase anterior (palavra e áudio), esperando o nome na próxima
        self._pending: tuple[list[dict], bytes] | None = None
        self.last_text = ""
        self.rejected = ""  # o que a segunda checagem ouviu, quando recusou
        self.last_volume = 0  # volume máximo da última fala, em % (para diagnosticar o microfone)
        self.near_miss = ""  # ouviu parte da frase, mas não ativou (vai para o registro)

    def feed(self, audio: bytes) -> bool:
        self._utterance += audio
        del self._utterance[:-MAX_UTTERANCE_BYTES]
        if not self._recognizer.AcceptWaveform(audio):
            return False
        return self._check(json.loads(self._recognizer.Result()))

    def flush(self) -> bool:
        """Fim do áudio (arquivos): avalia o que sobrou."""
        return self._check(json.loads(self._recognizer.FinalResult()))

    def _check(self, result: dict) -> bool:
        text = result.get("text", "")
        if text:
            self.last_text = text
        utterance, self._utterance = bytes(self._utterance), bytearray()
        self.last_volume = volume_percent(utterance)
        words = result.get("result") or []

        # Junta com o "olá" que ficou no fim da frase anterior (pausa da vírgula)
        pending_words, pending_audio = self._pending or ([], b"")
        combined = pending_words + words
        audio = pending_audio + utterance
        self._pending = None
        if words and words[-1]["word"] in GREETINGS:
            self._pending = ([words[-1]], utterance[-MAX_UTTERANCE_BYTES:])

        if not is_wake({"result": combined}, self.min_confidence):
            if NAME in text.split():
                confidences = ", ".join(f"{w['word']} {w['conf']:.2f}" for w in combined)
                self.near_miss = f"\"{' '.join(w['word'] for w in combined)}\" ({confidences})"
            return False
        self._pending = None
        free_text = self._transcribe(audio)
        if looks_confusable(free_text):
            self.rejected = free_text
            self.near_miss = f"\"{text}\", mas a segunda checagem ouviu \"{free_text}\""
            return False
        return True

    def _transcribe(self, audio: bytes) -> str:
        """Reconhecimento livre (vocabulário inteiro) do trecho. Só roda quando a gramática dispara."""
        recognizer = self._vosk.KaldiRecognizer(self._model, SAMPLE_RATE)
        parts = []
        for i in range(0, len(audio), BLOCK_SIZE * 2):
            if recognizer.AcceptWaveform(audio[i:i + BLOCK_SIZE * 2]):
                parts.append(json.loads(recognizer.Result()).get("text", ""))
        parts.append(json.loads(recognizer.FinalResult()).get("text", ""))
        return " ".join(p for p in parts if p)


# --- Abrir o assistente -------------------------------------------------------------------

def assistant_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/status", timeout=2) as response:
            return "assistant_name" in json.loads(response.read())
    except (OSError, ValueError):
        return False


def start_server() -> None:
    """Inicia o servidor sem janela, com o log num arquivo."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # python.exe (e não pythonw.exe): o servidor escreve no log; CREATE_NO_WINDOW esconde a janela
    python = Path(sys.executable).with_name("python.exe")
    if not python.exists():
        python = Path(sys.executable)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with (LOG_DIR / "servidor.log").open("a", encoding="utf-8") as out:
        subprocess.Popen(
            [str(python), "-m", "app"], cwd=BASE_DIR, stdout=out, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=flags,
        )


def open_assistant(settings: Settings) -> str:
    """Abre o painel, iniciando o servidor antes se preciso. Devolve o que fez."""
    from app.__main__ import open_when_ready  # evita importar o uvicorn só para escutar

    url = f"http://{HOST}:{settings.port}"
    if assistant_running(settings.port):
        webbrowser.open(url)
        return "painel aberto"
    start_server()
    open_when_ready(url, settings.port, timeout=60)
    return "servidor iniciado"


# --- Microfone -----------------------------------------------------------------------------

def microphone_blocks(stop_after: float | None = None):
    """Blocos de áudio do microfone padrão. Se ele sumir, espera e tenta de novo."""
    import sounddevice as sd

    blocks: queue.Queue[bytes] = queue.Queue(maxsize=40)

    def callback(indata, frames, time_info, status):
        try:
            blocks.put_nowait(bytes(indata))
        except queue.Full:
            pass  # processador ocupado: perder um pedaço de silêncio não faz diferença

    started = time.monotonic()
    while stop_after is None or time.monotonic() - started < stop_after:
        try:
            with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE, dtype="int16",
                                   channels=1, callback=callback):
                log.info("Microfone aberto. Diga \"Olá, Jarvis\".")
                while stop_after is None or time.monotonic() - started < stop_after:
                    yield blocks.get(timeout=10)
        except (sd.PortAudioError, queue.Empty) as exc:
            log.warning("Microfone indisponível (%s). Tentando de novo em %s s.", exc, MIC_RETRY_SECONDS)
            time.sleep(MIC_RETRY_SECONDS)


def listen(settings: Settings, detector: Detector, blocks, on_wake=open_assistant, clock=time.monotonic) -> None:
    last = float("-inf")
    for block in blocks:
        woke = detector.feed(block)
        if getattr(detector, "near_miss", ""):
            # Ajuda a calibrar: registra só quase ativações (nunca a conversa inteira)
            log.info("Quase ativou: ouvi %s, volume %s%%.", detector.near_miss, detector.last_volume)
            detector.near_miss = ""
        if woke and clock() - last >= COOLDOWN_SECONDS:
            last = clock()
            log.info("Ouvi a frase de ativação (volume %s%%): %s.", getattr(detector, "last_volume", "?"), on_wake(settings))


# --- Uma escuta por vez ----------------------------------------------------------------------

def single_instance(name: str = "Local\\JarvisEscuta"):
    """Trava do Windows para não rodar duas escutas. Devolve None se já houver outra."""
    if sys.platform != "win32":
        return object()
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, name)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return None
    return handle


# --- Modelo ----------------------------------------------------------------------------------

def download_model(target: Path = MODEL_DIR, url: str = MODEL_URL) -> Path:
    """Baixa e descompacta o modelo de voz, se ainda não existir."""
    if (target / "final.mdl").exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        archive = Path(tmp) / "modelo.zip"
        with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():  # nada de caminhos fora da pasta do modelo
                if member.startswith("/") or ".." in Path(member).parts:
                    raise ValueError("Arquivo do modelo inválido.")
            zf.extractall(tmp)
        shutil.move(str(Path(tmp) / target.name), str(target))
    return target


# --- Linha de comando -------------------------------------------------------------------------

def _setup_log(to_console: bool) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(LOG_DIR / "escuta.log", maxBytes=512_000, backupCount=2, encoding="utf-8"),
    ]
    if to_console and sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%d/%m %H:%M:%S")


def _test_file(path: Path, detector: Detector) -> bool:
    with wave.open(str(path), "rb") as wf:
        if wf.getframerate() != SAMPLE_RATE or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise SystemExit("O áudio precisa ser WAV de 16 kHz, mono, 16 bits.")
        heard = False
        while data := wf.readframes(BLOCK_SIZE):
            heard |= detector.feed(data)
    return heard or detector.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Escuta "Olá, Jarvis" e abre o painel.')
    parser.add_argument("--teste", action="store_true", help="mostra o que está ouvindo, sem abrir nada")
    parser.add_argument("--arquivo", type=Path, help="testa um áudio WAV (16 kHz, mono)")
    parser.add_argument("--baixar-modelo", action="store_true", help="baixa o modelo de voz, se faltar")
    args = parser.parse_args(argv)
    _setup_log(to_console=True)

    if args.baixar_modelo:
        print(f"Modelo de voz em {download_model()}")
        return 0
    if not (MODEL_DIR / "final.mdl").exists():
        log.error("Modelo de voz não encontrado. Rode: .\\escuta.ps1 -Instalar")
        return 1

    settings = get_settings()
    detector = Detector(min_confidence=settings.wake_min_confidence)

    if args.arquivo:
        heard = _test_file(args.arquivo, detector)
        print(f"{'ATIVARIA' if heard else 'não ativaria'}  (ouvi: \"{detector.last_text}\")")
        if detector.rejected:
            print(f"  a segunda checagem recusou: ouviu \"{detector.rejected}\"")
        return 0

    if args.teste:
        print('Modo de teste: fale "Olá, Jarvis" e outras frases. Ctrl+C para sair.', flush=True)
        print('(o modelo escreve "Jarvis" como "jarbas"; o que não for a frase aparece como [unk])', flush=True)
        for block in microphone_blocks():
            if detector.feed(block):
                print(f"  >>> ATIVARIA  (\"{detector.last_text}\", volume {detector.last_volume}%)", flush=True)
                detector.near_miss = ""
                detector.last_text = ""
            elif detector.rejected:
                print(f"      quase: parecia a frase, mas a segunda checagem ouviu \"{detector.rejected}\"", flush=True)
                detector.rejected = ""
                detector.near_miss = ""
                detector.last_text = ""
            elif detector.near_miss:
                print(f"      quase: {detector.near_miss}, volume {detector.last_volume}%", flush=True)
                detector.near_miss = ""
                detector.last_text = ""
            elif detector.last_text:
                print(f"      ouvi: \"{detector.last_text}\", volume {detector.last_volume}%", flush=True)
                detector.last_text = ""
        return 0

    lock = single_instance()
    if lock is None:
        log.info("Já existe uma escuta rodando; esta vai encerrar.")
        return 0
    log.info("Escuta iniciada (sensibilidade: confiança mínima %.2f).", settings.wake_min_confidence)
    listen(settings, detector, microphone_blocks())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
