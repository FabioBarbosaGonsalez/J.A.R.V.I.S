// Chamadas à API local.
//
// Para testar os estados de erro na Fase 1, abra a página com, por exemplo:
//   http://127.0.0.1:8000/?simular=email:erro,canvas:nao_configurado
//   http://127.0.0.1:8000/?simular=todos:erro

const TIMEOUT_MS = 15_000;
const SIM_STATES = {
  erro: 'error',
  error: 'error',
  nao_configurado: 'not_configured',
  not_configured: 'not_configured',
};

const simulation = parseSimulation(window.location.search);

function parseSimulation(search) {
  const raw = new URLSearchParams(search).get('simular');
  const result = {};
  if (!raw) return result;
  for (const pair of raw.split(',')) {
    const [name, state] = pair.split(':').map((s) => s?.trim());
    if (name && SIM_STATES[state]) result[name] = SIM_STATES[state];
  }
  return result;
}

export function panelUrl(name, path) {
  const state = simulation[name] ?? simulation.todos;
  return state ? `${path}?simulate=${state}` : path;
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { Accept: 'application/json', ...options.headers },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (err) {
    const message = err?.name === 'TimeoutError'
      ? 'O servidor demorou demais para responder.'
      : 'Sem conexão com o servidor local.';
    throw new Error(message);
  }
  if (!response.ok) throw new Error(`O servidor respondeu com erro ${response.status}.`);
  return response.json();
}

export const getJSON = (path) => request(path);

export const postJSON = (path, body) =>
  request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
