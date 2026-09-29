// Conexão com o Google: o botão "Conectar Google" pede ao servidor que abra o
// consentimento no navegador desta máquina e acompanha até terminar.

import { getJSON, postJSON } from './api.js';

const POLL_MS = 2000;
const MAX_WAIT_MS = 5.5 * 60_000; // o servidor desiste depois de 5 minutos

let polling = 0;

/**
 * Inicia a conexão. `refresh` redesenha os painéis: logo ao começar (para
 * mostrar "aguardando autorização") e de novo quando a conexão termina.
 */
export async function connectGoogle(refresh) {
  if (polling) return;
  let status;
  try {
    status = await postJSON('/api/google/connect', {});
  } catch {
    refresh();
    return;
  }
  refresh();
  if (status.state !== 'connecting') return;

  const started = Date.now();
  polling = setInterval(async () => {
    let current;
    try {
      current = await getJSON('/api/google/status');
    } catch {
      return; // servidor ocupado: tenta de novo no próximo ciclo
    }
    if (current.state !== 'connecting' || Date.now() - started > MAX_WAIT_MS) {
      clearInterval(polling);
      polling = 0;
      refresh();
    }
  }, POLL_MS);
}
