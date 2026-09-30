// Cartões de confirmação das ações propostas pela IA.
//
// A IA só propõe: nada é gravado antes do clique em Confirmar. O cartão
// expira em poucos minutos e só vale uma vez (o servidor garante as duas coisas;
// aqui só mostramos). O cartão de ativo no chat não traz números: quantidade,
// preço e o efeito na carteira aparecem só na aba privada.

import { postJSON } from './api.js';
import { h, icon } from './dom.js';

const WEEKDAYS = ['domingo', 'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado'];
const cards = new Map(); // id -> { settle(message, ok) }

const two = (n) => String(n).padStart(2, '0');
const hhmm = (d) => `${two(d.getHours())}:${two(d.getMinutes())}`;
const day = (d) => `${WEEKDAYS[d.getDay()]}, ${two(d.getDate())}/${two(d.getMonth() + 1)}/${d.getFullYear()}`;

function durationText(minutes) {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest} min`;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

function eventDetails(ev) {
  const start = new Date(ev.start);
  const rows = [['Data', day(start)]];
  if (ev.all_day) rows.push(['Horário', 'Dia inteiro']);
  else {
    rows.push(['Horário', `${hhmm(start)} às ${hhmm(new Date(ev.end))}`]);
    rows.push(['Duração', durationText(ev.duration_minutes)]);
  }
  return h('dl', { class: 'action-details' }, rows.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]));
}

/** Contagem regressiva até expirar. Devolve uma função que para a contagem. */
export function countdown(expiresAt, status, onExpire) {
  const deadline = new Date(expiresAt).getTime();
  const tick = () => {
    const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
    if (left <= 0) {
      clearInterval(timer);
      onExpire();
      return;
    }
    status.textContent = `Expira em ${Math.floor(left / 60)}:${two(left % 60)}`;
  };
  const timer = setInterval(tick, 1000);
  tick();
  return () => clearInterval(timer);
}

/**
 * Cartão para o chat.
 * `hooks.refreshCalendar()`: atualiza o painel da agenda depois de criar o evento.
 * `hooks.openPrivate()`: abre a aba "Minha carteira" (cartões de ativo).
 * `hooks.connectGoogle()`: reconecta o Google quando falta permissão.
 */
export function actionCard(card, hooks) {
  const status = h('p', { class: 'action-status', role: 'status' });
  const confirm = h('button', { class: 'btn', type: 'button' }, icon('check'), 'Confirmar');
  const review = h('button', { class: 'btn', type: 'button' }, icon('lock'), 'Revisar em Minha carteira');
  const cancel = h('button', { class: 'btn btn-ghost', type: 'button' }, 'Cancelar');
  const buttons = h('div', { class: 'action-buttons' }, card.kind === 'event' ? confirm : review, cancel);

  const body = card.kind === 'event'
    ? [h('p', { class: 'action-kind' }, 'Novo compromisso'),
      h('p', { class: 'action-title' }, card.event.title),
      eventDetails(card.event),
      h('p', { class: 'action-note' }, 'Agenda principal do Google. Nada é gravado antes de você confirmar.')]
    : [h('p', { class: 'action-kind' }, 'Inserir ativo na carteira'),
      h('p', { class: 'action-title' }, card.ticker),
      h('p', { class: 'action-note' }, 'Quantidade, preço e o efeito na carteira aparecem só na aba Minha carteira, protegida por chave.')];

  const box = h('div', { class: 'action-card', 'data-kind': card.kind }, ...body, buttons, status);

  let stop = () => {};
  const settle = (message, ok) => {
    stop();
    cards.delete(card.id);
    buttons.remove();
    box.classList.add(ok ? 'is-done' : 'is-closed');
    status.textContent = message;
  };
  stop = countdown(card.expires_at, status, () => settle('Expirou. Se ainda quiser, peça de novo.', false));
  cards.set(card.id, { settle });

  confirm.addEventListener('click', async () => {
    confirm.disabled = true;
    cancel.disabled = true;
    status.textContent = 'Confirmando…';
    try {
      const result = await postJSON(`/api/actions/${encodeURIComponent(card.id)}/confirm`, {});
      if (result.ok) {
        settle(result.message, true);
        hooks.refreshCalendar?.();
        return;
      }
      status.textContent = result.message;
      if (result.action === 'google_reconnect' && !buttons.querySelector('[data-reconnect]')) {
        buttons.append(h('button', {
          class: 'btn', type: 'button', 'data-reconnect': '', onclick: () => hooks.connectGoogle?.(),
        }, 'Reconectar Google'));
      }
    } catch (err) {
      if (err.status === 410) return settle(err.message, false);
      status.textContent = err.message;
    }
    confirm.disabled = false;
    cancel.disabled = false;
  });

  review.addEventListener('click', () => hooks.openPrivate?.());

  cancel.addEventListener('click', async () => {
    cancel.disabled = true;
    try {
      const result = await postJSON(`/api/actions/${encodeURIComponent(card.id)}/cancel`, {});
      settle(result.message, false);
    } catch (err) {
      settle(err.message, false);
    }
  });

  return h('div', { class: 'msg msg-action' }, box);
}

/** Avisa o cartão do chat que a ação foi resolvida em outro lugar (na aba privada). */
export function settleCard(id, message, ok) {
  cards.get(id)?.settle(message, ok);
}
