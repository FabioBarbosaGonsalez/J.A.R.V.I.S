// Painéis: carregamento independente, estados (carregando / ok / não configurado /
// erro) e renderização de cada fonte. Se uma fonte falhar, só o painel dela muda.

import { getJSON, panelUrl } from './api.js';
import { h, icon } from './dom.js';
import {
  ago, brl, dayDiff, dayLabel, hoursUntil, num, pct, shortDate, signedBrl, time, timeLeft, trendClass,
} from './format.js';
import { typeText } from './typewriter.js';

const DEADLINE_WINDOW_H = 7 * 24; // barra de prazo: 0% = 7 dias ou mais, 100% = vencendo
const URGENT_H = 48;
const TYPE_CLASS = { 'ação': 't-acao', FII: 't-fii', ETF: 't-etf', BDR: 't-bdr' };
const TYPE_LABEL = { 'ação': 'Ações', FII: 'FIIs', ETF: 'ETFs', BDR: 'BDRs' };

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

    const [chipClass, chipText] = done
      ? ['chip-done', 'Entregue']
      : overdue ? ['chip-overdue', 'Atrasada'] : ['chip-pending', 'Pendente'];

    const classes = ['item', 'task', urgent && 'is-urgent', done && 'is-done', overdue && 'is-overdue'];
    return h('li', { class: classes.filter(Boolean).join(' ') },
      h('div', { class: 'row' },
        h('span', { class: 'task-title', title: d.title }, d.title),
        h('span', { class: `chip ${chipClass}` }, chipText)),
      h('div', { class: 'row sub' },
        h('span', {}, d.course),
        h('span', { class: 'due', title: due.toLocaleString('pt-BR') },
          done ? `${shortDate(due)} · ${time(due)}` : timeLeft(hours))),
      h('div', { class: 'bar', 'aria-hidden': 'true' }, h('span', { style: `--p: ${progress.toFixed(3)}` })));
  })));
}

function renderPortfolio(body, pf) {
  const positions = [...pf.positions].sort((a, b) => b.market_value - a.market_value);

  const stat = (label, value, pctValue) =>
    h('div', {},
      h('span', { class: 'label' }, label),
      h('span', { class: `val ${trendClass(value)}` }, signedBrl(value), h('small', {}, pct(pctValue))));

  const allocation = h('div', {},
    h('div', { class: 'alloc-bar', role: 'img', 'aria-label': pf.allocation.map((a) => `${TYPE_LABEL[a.asset_type]} ${num(a.pct)}%`).join(', ') },
      pf.allocation.map((a) => h('span', { class: TYPE_CLASS[a.asset_type], style: `width: ${a.pct}%`, title: `${TYPE_LABEL[a.asset_type]}: ${brl(a.value)}` }))),
    h('ul', { class: 'alloc-legend' },
      pf.allocation.map((a) => h('li', {}, h('i', { class: TYPE_CLASS[a.asset_type] }), TYPE_LABEL[a.asset_type], h('b', {}, `${num(a.pct)}%`)))));

  const dividends = pf.dividends.length
    ? h('div', {},
      h('h3', { class: 'sub-title' }, 'Próximos proventos'),
      h('ul', { class: 'list compact' }, pf.dividends.map((d) =>
        h('li', { class: 'item' },
          h('span', { class: 'ticker' }, d.ticker),
          h('span', { class: 'muted' }, `${d.kind} · ${shortDate(new Date(`${d.payment_date}T12:00:00`))}`),
          h('span', { class: 'amount' }, `≈ ${brl(d.estimated_total)}`)))))
    : null;

  const table = h('div', {},
    h('h3', { class: 'sub-title' }, 'Posições'),
    h('table', { class: 'positions' },
      h('thead', {}, h('tr', {}, ['Ativo', 'Qtd', 'Preço', 'Dia', 'Resultado'].map((c) => h('th', { scope: 'col' }, c)))),
      h('tbody', {}, positions.map((p) => h('tr', {},
        h('td', {}, p.ticker),
        h('td', {}, num(p.quantity)),
        h('td', {}, brl(p.price)),
        h('td', { class: trendClass(p.day_change_pct) }, pct(p.day_change_pct)),
        h('td', { class: trendClass(p.result_pct) }, pct(p.result_pct)))))));

  body.replaceChildren(h('div', { class: 'pf' },
    h('div', {}, h('span', { class: 'label' }, 'Patrimônio'), h('strong', { class: 'big' }, brl(pf.total_value))),
    h('div', { class: 'pf-stats' },
      stat('Hoje', pf.day_change_value, pf.day_change_pct),
      stat('Sobre o preço médio', pf.result_value, pf.result_pct)),
    allocation,
    dividends,
    table,
    h('p', { class: 'disclaimer' }, 'Apenas uma descrição da carteira. Não é recomendação de investimento.')));
}

// --- Configuração dos painéis --------------------------------------------

export const PANELS = {
  briefing: {
    path: '/api/briefing',
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
    summary: (items) => `${items.filter((d) => d.status === 'pending').length} pendentes`,
  },
  portfolio: {
    path: '/api/portfolio',
    render: renderPortfolio,
    summary: (pf) => `${pf.positions.length} ativos`,
  },
};

// Painéis com tempo relativo ("há 3 h", "em 20 h") redesenhados a cada minuto
const TIME_SENSITIVE = ['calendar', 'email', 'canvas'];

// --- Estados ---------------------------------------------------------------

function skeleton(lines = 4) {
  return h('div', { class: 'skeleton', 'aria-hidden': 'true' }, Array.from({ length: lines }, () => h('span')));
}

function stateBlock(kind, title, message, onRetry) {
  return h('div', { class: `state state-${kind}` },
    icon(kind === 'error' ? 'alert' : 'plug'),
    h('p', { class: 'state-title' }, title),
    message && h('p', { class: 'state-msg' }, message),
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
    body.scrollTop = scroll;
    const parts = [cfg.summary?.(res.data), `às ${time(new Date(res.updated_at))}`];
    meta.textContent = parts.filter(Boolean).join(' · ');
    return;
  }
  meta.textContent = '';
  if (res.status === 'not_configured') {
    body.replaceChildren(stateBlock('off', 'Não configurado', res.message));
  } else {
    body.replaceChildren(stateBlock('error', 'Erro', res.message, () => loadPanel(name)));
  }
}

// --- API pública -------------------------------------------------------------

export async function loadPanel(name) {
  const { section, body } = elements(name);
  if (section.classList.contains('is-loading')) return;
  section.classList.add('is-loading');
  section.setAttribute('aria-busy', 'true');
  if (responses[name]?.status !== 'ok') body.replaceChildren(skeleton(name === 'briefing' ? 2 : 4));

  try {
    responses[name] = await getJSON(panelUrl(name, PANELS[name].path));
  } catch (err) {
    responses[name] = { status: 'error', message: err.message };
  }
  paint(name);
  section.classList.remove('is-loading');
  section.removeAttribute('aria-busy');
}

export const loadAll = () => Promise.all(Object.keys(PANELS).map(loadPanel));

export function repaintTimeSensitive() {
  for (const name of TIME_SENSITIVE) {
    if (responses[name]?.status === 'ok') paint(name);
  }
}

export const panelData = (name) => (responses[name]?.status === 'ok' ? responses[name].data : null);
