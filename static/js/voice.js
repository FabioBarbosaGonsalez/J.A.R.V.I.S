// Voz pelo navegador (Web Speech API), em pt-BR.
//
// - Ouvir: SpeechRecognition. No Chrome e no Edge o áudio é enviado ao serviço
//   de reconhecimento do próprio navegador, então precisa de internet.
// - Falar: speechSynthesis, com as vozes instaladas no Windows / no navegador.

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const LANG = 'pt-BR';
// Velocidade da fala (1 = normal do navegador). Um pouco acima do normal, ainda calma.
const SPEECH_RATE = 1.15;
const MAX_CHUNK = 180; // o Chrome costuma cortar falas longas; falamos em pedaços

// Vozes pt-BR masculinas e calmas, combinando com o tom de mordomo, em ordem de
// preferência: a neural do Edge e a instalada no Windows. Se não existirem,
// seguimos para as outras. O seletor de voz na interface vem na Fase 6.
const PREFERRED_VOICES = [/antonio/i, /daniel/i];

const ERRORS = {
  'not-allowed': 'Permissão do microfone negada. Libere o microfone no cadeado da barra de endereço.',
  'service-not-allowed': 'O navegador bloqueou o reconhecimento de voz.',
  'no-speech': 'Não ouvi nada. Tente de novo, mais perto do microfone.',
  'audio-capture': 'Nenhum microfone encontrado.',
  network: 'O reconhecimento de voz do navegador precisa de internet.',
  'language-not-supported': 'O reconhecimento deste navegador não suporta pt-BR.',
};

/** Divide o texto em frases e junta as curtas, respeitando MAX_CHUNK. */
function splitForSpeech(text) {
  const sentences = text.match(/[^.!?;:]+[.!?;:]*/g) ?? [text];
  const chunks = [];
  let current = '';
  for (const raw of sentences) {
    const sentence = raw.trim();
    if (!sentence) continue;
    if ((current + ' ' + sentence).length > MAX_CHUNK && current) {
      chunks.push(current);
      current = sentence;
    } else {
      current = current ? `${current} ${sentence}` : sentence;
    }
  }
  if (current) chunks.push(current);
  return chunks;
}

export function createVoice({ onListenStart, onInterim, onListenEnd, onError } = {}) {
  const canListen = Boolean(Recognition);
  const canSpeak = 'speechSynthesis' in window;

  let recognition = null;
  let finalText = '';
  let interimText = '';
  let voice = null;
  let speakToken = 0;

  function pickVoice() {
    const voices = window.speechSynthesis.getVoices();
    const ptBR = voices.filter((v) => v.lang?.replace('_', '-').toLowerCase() === 'pt-br');
    const preferred = PREFERRED_VOICES.map((re) => ptBR.find((v) => re.test(v.name))).find(Boolean);
    voice =
      preferred ||
      ptBR.find((v) => /natural|online/i.test(v.name)) || // vozes neurais do Edge
      ptBR.find((v) => /google/i.test(v.name)) ||
      ptBR[0] ||
      voices.find((v) => v.lang?.toLowerCase().startsWith('pt')) ||
      null;
  }

  if (canSpeak) {
    pickVoice();
    window.speechSynthesis.addEventListener('voiceschanged', pickVoice);
  }

  function listen({ continuous = false } = {}) {
    if (!canListen || recognition) return false;
    finalText = '';
    interimText = '';

    recognition = new Recognition();
    recognition.lang = LANG;
    recognition.interimResults = true;
    recognition.continuous = continuous;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => onListenStart?.();
    recognition.onresult = (event) => {
      finalText = '';
      interimText = '';
      for (const result of event.results) {
        if (result.isFinal) finalText += result[0].transcript;
        else interimText += result[0].transcript;
      }
      onInterim?.(`${finalText}${interimText}`.trim());
    };
    recognition.onerror = (event) => {
      if (event.error === 'aborted') return;
      onError?.(ERRORS[event.error] ?? `Erro no reconhecimento de voz (${event.error}).`);
    };
    recognition.onend = () => {
      recognition = null;
      // Se soltar a tecla antes do resultado final, aproveitamos o parcial.
      onListenEnd?.((finalText || interimText).trim());
    };

    try {
      recognition.start();
    } catch {
      recognition = null;
      onError?.('Não foi possível iniciar o microfone.');
      return false;
    }
    return true;
  }

  function stopListening() {
    recognition?.stop();
  }

  function abortListening() {
    if (!recognition) return;
    finalText = '';
    interimText = '';
    recognition.abort();
  }

  /**
   * Fala o texto. Uma nova fala interrompe a anterior.
   * `onEnd` é chamado ao terminar naturalmente (não quando é interrompida).
   */
  function speak(text, { onStart, onBoundary, onEnd } = {}) {
    if (!canSpeak || !text) {
      onEnd?.();
      return;
    }
    const token = ++speakToken;
    const synth = window.speechSynthesis;
    const wasBusy = synth.speaking || synth.pending;
    synth.cancel();

    const chunks = splitForSpeech(text);
    let index = 0;
    let started = false;

    const next = () => {
      if (token !== speakToken) return;
      if (index >= chunks.length) {
        onEnd?.();
        return;
      }
      const utterance = new SpeechSynthesisUtterance(chunks[index++]);
      utterance.lang = LANG;
      if (voice) utterance.voice = voice;
      utterance.rate = SPEECH_RATE;
      utterance.onstart = () => {
        if (!started) {
          started = true;
          onStart?.();
        }
      };
      utterance.onboundary = (event) => {
        if (!event.name || event.name === 'word') onBoundary?.();
      };
      utterance.onend = next;
      utterance.onerror = (event) => {
        if (event.error === 'interrupted' || event.error === 'canceled') return;
        next();
      };
      synth.speak(utterance);
    };

    // O Chrome às vezes ignora um speak() logo após cancel(); um pequeno atraso resolve.
    if (wasBusy) setTimeout(next, 60);
    else next();
  }

  function stopSpeaking() {
    speakToken++;
    if (canSpeak) window.speechSynthesis.cancel();
  }

  return {
    canListen,
    canSpeak,
    get listening() {
      return recognition !== null;
    },
    listen,
    stopListening,
    abortListening,
    speak,
    stopSpeaking,
  };
}
