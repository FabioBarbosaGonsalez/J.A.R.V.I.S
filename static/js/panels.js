// Painéis: carregamento independente, estados (carregando / ok / não configurado /
// erro) e renderização de cada fonte. Se uma fonte falhar, só o painel dela muda.

import { AI_TIMEOUT_MS, getJSON, panelUrl } from './api.js';
import { h, icon } from './dom.js';
import { connectGoogle } from './google.js';
import {
  ago, brl, brl4, dayDiff, dayLabel, hoursUntil, pct, shortDate, time, timeLeft, trendClass, usd,
} from './format.js';
import { typeText } from './typewriter.js';

const DEADLINE_WINDOW_H = 7 * 24; // barra de prazo: 0% = 7 dias ou mais, 100% = vencendo
const URGENT_H = 48;
const TYPE_ORDER = ['ação', 'FII', 'ETF', 'BDR', 'ETF Internacional', 'Tesouro Direto'];
const TYPE_LABEL = {
  'ação': 'Ações', FII: 'FIIs', ETF: 'ETFs', BDR: 'BDRs',
  'ETF Internacional': 'ETFs internacionais', 'Tesouro Direto': 'Tesouro Direto',
};

const responses = {}; // última resposta de cada painel

// --- Renderizadores ------------------------------------------------------

function renderBriefing(body, briefing) {
  let text = body.querySelector('.briefing-text');
  let chips = body.querySelector('.chips');
  if (!text) {
    text = h('p', { class: 'briefing-text' });
    chips = h('ul', { class: 'chips', 'aria-label': 'Destaques' });
    body.replaceChildren(h('div', { class: 'briefing' }, text, chips));
  }
  // Só digita de novo quando o texto muda
  if (text.dataset.text !== briefing.text) {
    text.dataset.text = briefing.text;
    typeText(text, briefing.text, { cps: 75 });
  }
  chips.replaceChildren(
    ...briefing.highlights.map((hl) => h('li', { class: `chip chip-${hl.level}` }, hl.text)),
  );
}

function renderCalendar(body, events) {
  const now = new Date();
  const upcoming = events.filter((ev) => new Date(ev.end) > now || dayDiff(new Date(ev.start), now) === 0);
  if (!upcoming.length) {
    body.replaceChildren(h('p', { class: 'empty' }, 'Nenhum compromisso nos próximos 7 dias.'));
    return;
  }

  const groups = new Map();
  for (const ev of upcoming) {
    const start = new Date(ev.start);
    const key = start.toDateString();
    if (!groups.has(key)) groups.set(key, { date: start, items: [] });
    groups.get(key).items.push(ev);
  }

  const nodes = [];
  for (const { date, items } of groups.values()) {
    nodes.push(h('h3', { class: 'day-label' }, dayLabel(date, now)));
    nodes.push(h('ul', { class: 'list' }, items.map((ev) => {
      const start = new Date(ev.start);
      const end = new Date(ev.end);
      const past = end <= now;
      const current = !ev.all_day && start <= now && now < end;
      return h('li', { class: `item event${past ? ' is-past' : ''}${current ? ' is-now' : ''}` },
        h('span', { class: 'event-time' },
          ev.all_day ? 'Dia todo' : time(start),
          !ev.all_day && h('small', {}, time(end))),
        h('div', {},
          h('div', { class: 'event-title' }, current && h('span', { class: 'sr-only' }, 'Agora: '), ev.title),
          ev.location && h('div', { class: 'event-loc' }, ev.location)));
    })));
  }
  body.replaceChildren(...nodes);
}

function renderEmails(body, emails) {
  if (!emails.length) {
    body.replaceChildren(h('p', { class: 'empty' }, 'Caixa de entrada vazia.'));
    return;
  }
  const now = new Date();
  body.replaceChildren(h('ul', { class: 'list' }, emails.map((e) => {
    const received = new Date(e.received_at);
    const classes = ['item', 'email', e.unread && 'is-unread', e.from_university && 'is-university'];
    return h('li', { class: classes.filter(Boolean).join(' ') },
      h('div', { class: 'row' },
        h('span', { class: 'dot', 'aria-hidden': 'true' }),
        h('span', { class: 'sender', title: e.sender_email }, e.sender_name),
        e.from_university && h('span', { class: 'tag' }, 'Faculdade'),
        h('time', { class: 'when', datetime: e.received_at, title: received.toLocaleString('pt-BR') }, ago(received, now))),
      h('div', { class: 'subject' }, e.unread && h('span', { class: 'sr-only' }, 'Não lido: '), e.subject),
      h('div', { class: 'snippet' }, e.snippet));
  })));
}

function renderCanvas(body, deliverables) {
  if (!deliverables.length) {
    body.replaceChildren(h('p', { class: 'empty' }, 'Nenhuma entrega nos próximos dias.'));
    return;
  }
  const now = new Date();
  body.replaceChildren(h('ul', { class: 'list' }, deliverables.map((d) => {
    const due = new Date(d.due_at);
    const hours = hoursUntil(due, now);
    const done = d.status === 'submitted';
    const overdue = !done && hours <= 0;
    const urgent = !done && hours > 0 && hours < URGENT_H;
    const progress = Math.min(1, Math.max(0, 1 - hours / DEADLINE_WINDOW_H));

    // "unknown": veio do feed do calendário, que não diz se foi entregue
    const [chipClass, chipText] = done
      ? ['chip-done', 'Entregue']
      : overdue ? ['chip-overdue', 'Atrasada']
        : d.status === 'pending' ? ['chip-pending', 'Pendente'] : [null, null];

    const title = d.url?.startsWith('https://')
      ? h('a', { href: d.url, target: '_blank', rel: 'noopener noreferrer', title: `${d.title} (abrir no Canvas)` }, d.title)
      : d.title;

    const classes = ['item', 'task', urgent && 'is-urgent', done && 'is-done', overdue && 'is-overdue'];
    return h('li', { class: classes.filter(Boolean).join(' ') },
      h('div', { class: 'row' },
        h('span', { class: 'task-title', title: d.title }, title),
        chipText && h('span', { class: `chip ${chipClass}` }, chipText)),
      h('div', { class: 'row sub' },
        h('span', {}, d.course),
        h('span', { class: 'due', title: due.toLocaleString('pt-BR') },
          done ? `${shortDate(due)} · ${time(due)}` : timeLeft(hours))),
      h('div', { class: 'bar', 'aria-hidden': 'true' }, h('span', { style: `--p: ${progress.toFixed(3)}` })));
  })));
}

// Mercado: dólar ao vivo e cotação de cada ativo da carteira. De propósito, sem
// quantidade, patrimônio ou resultado: a home não mostra quanto está investido.
function renderMarket(body, market) {
  const fx = market.usd_brl;
  const dollar = fx
    ? h('div', { class: 'fx' },
      h('div', {},
        h('span', { class: 'label' }, 'Dólar comercial'),
        h('strong', { class: 'big' }, brl4(fx.bid))),
      h('div', { class: 'fx-side' },
        h('span', { class: `val ${trendClass(fx.pct_change)}` }, pct(fx.pct_change)),
        h('small', {}, `mín ${brl4(fx.low)} · máx ${brl4(fx.high)}`),
        h('small', {}, `atualizado às ${time(new Date(fx.updated_at))}`)))
    : h('p', { class: 'empty' }, 'Cotação do dólar indisponível no momento.');

  // Agrupa por tipo, na ordem de TYPE_ORDER
  const groups = TYPE_ORDER
    .map((type) => [type, market.quotes.filter((q) => q.asset_type === type)])
    .filter(([, items]) => items.length);

  const rows = groups.flatMap(([type, items]) => [
    h('tr', { class: 'group' }, h('th', { colspan: 3, scope: 'colgroup' }, TYPE_LABEL[type])),
    ...items.map((q) => (q.price == null
      ? h('tr', { class: 'no-quote' },
        h('th', { scope: 'row' }, q.ticker),
        h('td', { colspan: 2 }, q.note ?? 'Sem cotação.'))
      : h('tr', {},
        h('th', { scope: 'row', title: q.name ?? '' }, q.ticker),
        h('td', {}, q.currency === 'USD' ? usd(q.price) : brl(q.price)),
        h('td', { class: trendClass(q.change_pct) }, pct(q.change_pct))))),
  ]);

  body.replaceChildren(h('div', { class: 'market' },
    dollar,
    h('div', {},
      h('h3', { class: 'sub-title' }, 'Cotações da carteira'),
      h('table', { class: 'quotes' },
        h('thead', {}, h('tr', {}, ['Ativo', 'Preço', 'Dia'].map((c) => h('th', { scope: 'col' }, c)))),
        h('tbody', {}, rows))),
    h('p', { class: 'disclaimer' }, 'Cotações com até 30 minutos de atraso (plano gratuito da brapi). Não é recomendação de investimento.')));
}

// --- Configuração dos painéis --------------------------------------------

export const PANELS = {
  briefing: {
    path: '/api/briefing',
    timeoutMs: AI_TIMEOUT_MS,
    render: renderBriefing,
    summary: (b) => (b.generator === 'ai' ? 'gerado por IA' : 'gerado por regras'),
  },
  calendar: {
    path: '/api/calendar',
    render: renderCalendar,
    summary: (events) => {
      const today = events.filter((ev) => dayDiff(new Date(ev.start)) === 0 && !ev.all_day).length;
      return `${today} hoje`;
    },
  },
  email: {
    path: '/api/emails',
    render: renderEmails,
    summary: (emails) => `${emails.filter((e) => e.unread).length} não lidos`,
  },
  canvas: {
    path: '/api/canvas',
    render: renderCanvas,
    summary: (items) => `${items.filter((d) => d.status !== 'submitted').length} em aberto`,
  },
  market: {
    path: '/api/market',
    render: renderMarket,
    summary: (m) => `${m.quotes.filter((q) => q.price != null).length} de ${m.quotes.length} cotados`,
  },
};

// Painéis com tempo relativo ("há 3 h", "em 20 h") redesenhados a cada minuto
const TIME_SENSITIVE = ['calendar', 'email', 'canvas'];

// Fontes de dados mostradas no diagnóstico do cabeçalho (o briefing deriva delas)
const SYSTEMS = { calendar: 'Agenda', email: 'E-mails', canvas: 'Faculdade', market: 'Mercado' };
const STATUS_LABEL = { ok: 'online', not_configured: 'não configurado', error: 'erro' };

// --- Diagnóstico dos sistemas -----------------------------------------------

function updateSystems() {
  const names = Object.keys(SYSTEMS);
  const statuses = names.map((name) => responses[name]?.status);
  if (statuses.some((s) => s === undefined)) return; // ainda carregando pela primeira vez

  const online = statuses.filter((s) => s === 'ok').length;
  const level = online === names.length ? 'ok' : statuses.includes('error') ? 'error' : 'partial';

  const container = document.getElementById('sys-status');
  container.dataset.level = level;
  container.title = names.map((name, i) => `${SYSTEMS[name]}: ${STATUS_LABEL[statuses[i]]}`).join('\n');

  document.getElementById('sys-dots').replaceChildren(
    ...names.map((name, i) => h('i', { class: `sys-dot is-${statuses[i]}` })),
  );
  // Só troca o texto quando muda, para leitores de tela não repetirem o anúncio
  const count = document.getElementById('sys-count');
  const text = `${online}/${names.length} online`;
  if (count.textContent !== text) count.textContent = text;
}

// --- Estados ---------------------------------------------------------------

function skeleton(lines = 4) {
  return h('div', { class: 'skeleton', 'aria-hidden': 'true' }, Array.from({ length: lines }, () => h('span')));
}

// Botões que o servidor pode oferecer num painel sem dados (PanelResponse.action)
const ACTIONS = {
  google_connect: { label: 'Conectar Google', icon: 'plug' },
  google_reconnect: { label: 'Reconectar Google', icon: 'refresh' },
};

// Gmail e Agenda dependem da mesma conexão: redesenha os dois, e o briefing
export function refreshGooglePanels() {
  loadPanel('email', { force: true });
  loadPanel('calendar', { force: true });
  loadPanel('briefing');
}

function stateBlock(kind, title, message, onRetry, action) {
  const actionButton = ACTIONS[action] && h('button', {
    class: 'btn', type: 'button', onclick: () => connectGoogle(refreshGooglePanels),
  }, icon(ACTIONS[action].icon), ACTIONS[action].label);

  return h('div', { class: `state state-${kind}` },
    icon(kind === 'error' ? 'alert' : 'plug'),
    h('p', { class: 'state-title' }, title),
    message && h('p', { class: 'state-msg' }, message),
    actionButton,
    onRetry && h('button', { class: 'btn', type: 'button', onclick: onRetry }, icon('refresh'), 'Tentar de novo'));
}

function elements(name) {
  const section = document.querySelector(`[data-panel="${name}"]`);
  return { section, body: section.querySelector('[data-body]'), meta: section.querySelector('[data-meta]') };
}

function paint(name) {
  const { section, body, meta } = elements(name);
  const res = responses[name];
  const cfg = PANELS[name];
  section.dataset.status = res.status;

  if (res.status === 'ok') {
    const scroll = body.scrollTop; // redesenhar não pode jogar a rolagem para o topo
    cfg.render(body, res.data);
    body.querySelector(':scope > .panel-note')?.remove();
    if (res.message) body.prepend(h('p', { class: 'panel-note' }, icon('alert'), res.message));
    body.scrollTop = scroll;
    const when = `${res.source === 'cache' ? 'dados de' : 'às'} ${time(new Date(res.updated_at))}`;
    const parts = [cfg.summary?.(res.data), when];
    meta.textContent = parts.filter(Boolean).join(' · ');
    return;
  }
  meta.textContent = '';
  if (res.status === 'not_configured') {
    const title = { google_reconnect: 'Conexão expirada', google_waiting: 'Conectando' }[res.action] ?? 'Não configurado';
    body.replaceChildren(stateBlock('off', title, res.message, null, res.action));
  } else {
    body.replaceChildren(stateBlock('error', 'Erro', res.message, () => loadPanel(name, { force: true })));
  }
}

// --- API pública -------------------------------------------------------------

export async function loadPanel(name, { force = false } = {}) {
  const { section, body } = elements(name);
  if (section.classList.contains('is-loading')) return;
  section.classList.add('is-loading');
  section.setAttribute('aria-busy', 'true');
  if (responses[name]?.status !== 'ok') body.replaceChildren(skeleton(name === 'briefing' ? 2 : 4));

  try {
    const { path, timeoutMs } = PANELS[name];
    responses[name] = await getJSON(panelUrl(name, path, { force }), { timeoutMs });
  } catch (err) {
    responses[name] = { status: 'error', message: err.message };
  }
  paint(name);
  updateSystems();
  section.classList.remove('is-loading');
  section.removeAttribute('aria-busy');
}

/** Carrega as fontes em paralelo e o briefing por último, para ele já usar os dados novos. */
export async function loadAll({ force = false } = {}) {
  const sources = Object.keys(PANELS).filter((name) => name !== 'briefing');
  await Promise.all(sources.map((name) => loadPanel(name, { force })));
  await loadPanel('briefing');
}

export function repaintTimeSensitive() {
  for (const name of TIME_SENSITIVE) {
    if (responses[name]?.status === 'ok') paint(name);
  }
}

export const panelData = (name) => (responses[name]?.status === 'ok' ? responses[name].data : null);
