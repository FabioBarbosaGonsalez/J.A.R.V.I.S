// Ponto de entrada da interface: liga núcleo, voz, conversa e painéis.

import { getJSON, postJSON } from './api.js';
import { createCore } from './core.js';
import { h } from './dom.js';
import { loadAll, loadPanel, panelData, repaintTimeSensitive } from './panels.js';
import { typeText } from './typewriter.js';
import { createVoice } from './voice.js';

const STATE_LABELS = {
  idle: 'Em espera',
  listening: 'Ouvindo',
  thinking: 'Processando',
  speaking: 'Falando',
};
const MAX_MESSAGES = 40;

const $ = (selector) => document.querySelector(selector);
const ui = {
  core: createCore($('#core')),
  coreState: $('#core-state'),
  transcript: $('#transcript'),
  form: $('#composer'),
  input: $('#chat-input'),
  mic: $('#mic-btn'),
  voiceToggle: $('#voice-toggle'),
  hint: $('#voice-hint'),
  refreshAll: $('#refresh-all'),
};

let assistantName = 'J.A.R.V.I.S';
let refreshMs = 300_000;
let lastRefresh = 0;
let speakEnabled = readPref('speak', true);
let pushToTalk = false;
let interimMessage = null;
let busy = false;

// --- Preferências locais (só conveniência; pode falhar em janela anônima) ---

function readPref(key, fallback) {
  try {
    const value = localStorage.getItem(`hud.${key}`);
    return value === null ? fallback : JSON.parse(value);
  } catch {
    return fallback;
  }
}

function writePref(key, value) {
  try {
    localStorage.setItem(`hud.${key}`, JSON.stringify(value));
  } catch { /* sem armazenamento: tudo bem */ }
}

// --- Núcleo -------------------------------------------------------------------

function setCoreState(state) {
  ui.core.setState(state);
  ui.coreState.textContent = STATE_LABELS[state];
  document.body.dataset.state = state;
}

// --- Conversa -----------------------------------------------------------------

function addMessage(role, text = '') {
  const who = role === 'user' ? 'Você' : role === 'ai' ? assistantName : 'Sistema';
  const paragraph = h('p', {}, text);
  ui.transcript.append(h('div', { class: `msg msg-${role}` }, h('span', { class: 'msg-who' }, who), paragraph));
  while (ui.transcript.childElementCount > MAX_MESSAGES) ui.transcript.firstElementChild.remove();
  scrollTranscript();
  return paragraph;
}

function scrollTranscript() {
  ui.transcript.scrollTop = ui.transcript.scrollHeight;
}

// Mantém a conversa rolada até o fim enquanto o texto é digitado
new MutationObserver(scrollTranscript).observe(ui.transcript, { childList: true, subtree: true, characterData: true });

/** Mostra a resposta digitando e, se a voz estiver ligada, fala ao mesmo tempo. */
function respond(text, target = addMessage('ai')) {
  const typing = typeText(target, text, { cps: 45 });

  if (speakEnabled && voice.canSpeak) {
    voice.speak(text, {
      onStart: () => setCoreState('speaking'),
      onBoundary: () => ui.core.pulse(0.45),
      onEnd: () => setCoreState('idle'),
    });
    // Se nenhuma voz começar a falar (ex.: sem vozes pt-BR), não fica preso em "Processando"
    typing.then(() => {
      if (ui.core.state === 'thinking') setCoreState('idle');
    });
  } else {
    setCoreState('speaking');
    typing.then(() => setCoreState('idle'));
  }
}

async function ask(text) {
  const message = text.trim();
  if (!message || busy) return;
  busy = true;
  voice.stopSpeaking();
  addMessage('user', message);
  setCoreState('thinking');
  try {
    const { reply } = await postJSON('/api/chat', { message });
    respond(reply);
  } catch (err) {
    addMessage('system', `Não consegui responder agora. ${err.message}`);
    setCoreState('idle');
  } finally {
    busy = false;
  }
}

// --- Voz ----------------------------------------------------------------------

const voice = createVoice({
  onListenStart() {
    setCoreState('listening');
    ui.mic.setAttribute('aria-pressed', 'true');
  },
  onInterim(text) {
    if (!interimMessage) {
      interimMessage = addMessage('user');
      interimMessage.parentElement.classList.add('is-interim');
    }
    interimMessage.textContent = text || '…';
  },
  onListenEnd(text) {
    ui.mic.setAttribute('aria-pressed', 'false');
    pushToTalk = false;
    interimMessage?.parentElement.remove();
    interimMessage = null;
    if (text) ask(text);
    else if (ui.core.state === 'listening') setCoreState('idle');
  },
  onError(message) {
    addMessage('system', message);
  },
});

function startListening(continuous) {
  if (!voice.canListen) {
    addMessage('system', 'Reconhecimento de voz indisponível neste navegador. Use o Chrome ou o Edge.');
    return false;
  }
  voice.stopSpeaking();
  return voice.listen({ continuous });
}

function stopEverything() {
  voice.abortListening();
  voice.stopSpeaking();
  if (ui.core.state !== 'thinking') setCoreState('idle');
}

function updateVoiceToggle() {
  ui.voiceToggle.setAttribute('aria-pressed', String(speakEnabled));
  ui.voiceToggle.setAttribute('aria-label', `Respostas faladas: ${speakEnabled ? 'ligadas' : 'desligadas'}`);
  ui.voiceToggle.title = speakEnabled ? 'Desligar respostas faladas' : 'Ligar respostas faladas';
  ui.voiceToggle.querySelector('use').setAttribute('href', speakEnabled ? '#i-volume' : '#i-volume-off');
}

const isTypingTarget = (el) =>
  el instanceof HTMLElement && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));

// Segurar Espaço = falar (push-to-talk). Ignorado enquanto você digita num campo.
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    stopEverything();
    return;
  }
  if (event.code !== 'Space' || isTypingTarget(event.target) || event.ctrlKey || event.altKey || event.metaKey) return;
  event.preventDefault(); // não rolar a página nem "clicar" o botão focado
  if (event.repeat || pushToTalk || voice.listening) return;
  pushToTalk = startListening(true);
});

document.addEventListener('keyup', (event) => {
  if (event.code !== 'Space' || isTypingTarget(event.target)) return;
  event.preventDefault();
  if (pushToTalk) voice.stopListening();
});

// Se a janela perder o foco com o Espaço apertado, o keyup nunca chega
window.addEventListener('blur', () => {
  if (pushToTalk) voice.stopListening();
});

ui.mic.addEventListener('click', () => {
  if (voice.listening) voice.stopListening();
  else startListening(false); // clique: para sozinho quando você fica em silêncio
});

ui.voiceToggle.addEventListener('click', () => {
  speakEnabled = !speakEnabled;
  writePref('speak', speakEnabled);
  if (!speakEnabled) {
    voice.stopSpeaking();
    if (ui.core.state === 'speaking') setCoreState('idle');
  }
  updateVoiceToggle();
});

ui.form.addEventListener('submit', (event) => {
  event.preventDefault();
  const text = ui.input.value;
  ui.input.value = '';
  ask(text);
});

// --- Painéis ------------------------------------------------------------------

async function refreshAll() {
  lastRefresh = Date.now();
  ui.refreshAll.classList.add('is-loading');
  await loadAll();
  ui.refreshAll.classList.remove('is-loading');
}

document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const panel = button.closest('[data-panel]')?.dataset.panel;
  if (button.dataset.action === 'refresh' && panel) loadPanel(panel);
  if (button.dataset.action === 'speak-briefing') {
    const briefing = panelData('briefing');
    if (!briefing) return;
    if (!voice.canSpeak) {
      addMessage('system', 'Este navegador não tem síntese de voz.');
      return;
    }
    voice.speak(briefing.text, {
      onStart: () => setCoreState('speaking'),
      onBoundary: () => ui.core.pulse(0.45),
      onEnd: () => setCoreState('idle'),
    });
  }
});

ui.refreshAll.addEventListener('click', refreshAll);

// Atualização automática; pausa com a aba escondida e recupera ao voltar
function scheduleRefresh() {
  setInterval(() => {
    if (!document.hidden && Date.now() - lastRefresh >= refreshMs) refreshAll();
  }, 15_000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && Date.now() - lastRefresh >= refreshMs) refreshAll();
  });
}

// --- Relógio ------------------------------------------------------------------

function tickClock() {
  const now = new Date();
  $('#clock-time').textContent = now.toLocaleTimeString('pt-BR');
  $('#clock-date').textContent = now.toLocaleDateString('pt-BR', { weekday: 'long', day: 'numeric', month: 'long' });
}

// --- Início -------------------------------------------------------------------

async function init() {
  tickClock();
  setInterval(tickClock, 1000);
  setInterval(repaintTimeSensitive, 60_000);
  updateVoiceToggle();

  if (!voice.canListen) {
    ui.mic.disabled = true;
    ui.mic.title = 'Reconhecimento de voz indisponível neste navegador';
    ui.hint.textContent = 'Voz indisponível neste navegador. Use o Chrome ou o Edge para falar.';
  }

  try {
    const status = await getJSON('/api/status');
    assistantName = status.assistant_name;
    refreshMs = Math.max(30, status.refresh_seconds) * 1000;
    document.title = assistantName;
    $('#assistant-name').textContent = assistantName;
    $('#core-name').textContent = assistantName;
    $('#mode-badge').hidden = !status.demo_mode;
  } catch (err) {
    addMessage('system', err.message);
  }

  await refreshAll();
  scheduleRefresh();

  const hint = voice.canListen ? 'Pergunte algo ou segure Espaço para falar.' : 'Pergunte algo pelo campo de texto.';
  typeText(addMessage('ai'), `Sistemas online. ${hint}`, { cps: 45 });
}

init();
