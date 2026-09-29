// Aba privada "Minha carteira".
//
// A chave é conferida no servidor; aqui só existe o formulário. A sessão fica
// num cookie HttpOnly que este código nem consegue ler. Os dados da carteira só
// existem no DOM enquanto a janela está aberta: fechar, bloquear ou trocar de
// aba/minimizar apaga tudo da tela.

import { getJSON, postJSON } from './api.js';
import { h, icon } from './dom.js';
import { brl, num, pct, signedBrl, trendClass, usd } from './format.js';

const TYPE_LABEL = {
  'ação': 'Ações', FII: 'FIIs', ETF: 'ETFs', BDR: 'BDRs',
  'ETF Internacional': 'ETFs internacionais', 'Tesouro Direto': 'Tesouro Direto',
};
const TYPE_CLASS = {
  'ação': 't-acao', FII: 't-fii', ETF: 't-etf', BDR: 't-bdr',
  'ETF Internacional': 't-intl', 'Tesouro Direto': 't-td',
};

const dialog = document.getElementById('private-dialog');
const content = dialog.querySelector('[data-content]');
let countdown = 0;

const money = (value, currency) => (currency === 'USD' ? usd(value) : brl(value));

// 404 nas rotas da aba = servidor iniciado antes de a aba existir (código atualizado
// sem reiniciar). Explica isso em vez de mostrar um "Not Found" sem sentido.
const OUTDATED = 'O servidor está rodando uma versão anterior, sem esta aba. Reinicie o servidor e tente de novo.';
const explain = (err) => (err.status === 404 ? OUTDATED : err.message);

function clear() {
  clearInterval(countdown);
  content.replaceChildren();
}

function close() {
  clear();
  if (dialog.open) dialog.close();
}

// --- Telas ---------------------------------------------------------------------

function showMessage(title, message) {
  content.replaceChildren(h('div', { class: 'private-lock' },
    icon('lock', 'icon icon-xl'),
    h('p', { class: 'state-title' }, title),
    h('p', { class: 'state-msg' }, message)));
}

function showUnlockForm(notice = '') {
  const input = h('input', {
    class: 'chat-input', type: 'password', id: 'private-key', autocomplete: 'off',
    spellcheck: 'false', maxlength: '200', required: true,
  });
  const status = h('p', { class: 'private-status', role: 'alert' }, notice);
  const submit = h('button', { class: 'btn', type: 'submit' }, icon('lock'), 'Desbloquear');

  const form = h('form', { class: 'private-lock', autocomplete: 'off' },
    icon('lock', 'icon icon-xl'),
    h('p', { class: 'state-title' }, 'Área protegida'),
    h('label', { class: 'state-msg', for: 'private-key' }, 'Digite a sua chave de acesso.'),
    input, submit, status);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    submit.disabled = true;
    try {
      await postJSON('/api/private/unlock', { key: input.value });
      input.value = '';
      await showPortfolio();
    } catch (err) {
      input.value = '';
      status.textContent = explain(err);
      if (err.retryAfter) waitThenEnable(submit, status, err.retryAfter);
      else submit.disabled = false;
      input.focus();
    }
  });

  content.replaceChildren(form);
  input.focus();
}

function waitThenEnable(button, status, seconds) {
  clearInterval(countdown);
  let left = seconds;
  countdown = setInterval(() => {
    left -= 1;
    status.textContent = left > 0 ? `Muitas tentativas. Aguarde ${left} s.` : '';
    if (left <= 0) {
      clearInterval(countdown);
      button.disabled = false;
    }
  }, 1000);
}

async function showPortfolio() {
  content.replaceChildren(h('p', { class: 'empty' }, 'Carregando carteira…'));
  let res;
  try {
    res = await getJSON('/api/private/portfolio');
  } catch (err) {
    if (err.status === 401) return showUnlockForm('Sessão encerrada. Digite a chave novamente.');
    return showMessage(err.status === 404 ? 'Servidor desatualizado' : 'Erro', explain(err));
  }
  if (res.status !== 'ok') return showMessage(res.status === 'error' ? 'Erro' : 'Não configurado', res.message);
  renderPortfolio(res.data, res.message);
}

function renderPortfolio(pf, note) {
  const positions = [...pf.positions].sort((a, b) => b.market_value - a.market_value);

  const stat = (label, value, pctValue) =>
    h('div', {},
      h('span', { class: 'label' }, label),
      h('span', { class: `val ${trendClass(value)}` }, signedBrl(value), h('small', {}, pct(pctValue))));

  const allocation = pf.allocation.length > 0 && h('div', {},
    h('div', { class: 'alloc-bar', role: 'img', 'aria-label': pf.allocation.map((a) => `${TYPE_LABEL[a.asset_type]} ${num(a.pct)}%`).join(', ') },
      pf.allocation.map((a) => h('span', { class: TYPE_CLASS[a.asset_type], style: `width: ${a.pct}%`, title: `${TYPE_LABEL[a.asset_type]}: ${brl(a.value)}` }))),
    h('ul', { class: 'alloc-legend' },
      pf.allocation.map((a) => h('li', {}, h('i', { class: TYPE_CLASS[a.asset_type] }), TYPE_LABEL[a.asset_type], h('b', {}, `${num(a.pct)}%`)))));

  const table = h('div', { class: 'table-wrap' },
    h('table', { class: 'quotes positions' },
      h('thead', {}, h('tr', {}, ['Ativo', 'Qtd', 'Preço médio', 'Preço', 'Valor (R$)', 'Dia', 'Resultado'].map((c) => h('th', { scope: 'col' }, c)))),
      h('tbody', {}, positions.map((p) => h('tr', {},
        h('th', { scope: 'row' }, p.ticker),
        h('td', {}, num(p.quantity)),
        h('td', {}, money(p.avg_price, p.currency)),
        h('td', {}, money(p.price, p.currency)),
        h('td', {}, brl(p.market_value)),
        h('td', { class: trendClass(p.day_change_pct) }, pct(p.day_change_pct)),
        h('td', { class: trendClass(p.result_pct) }, pct(p.result_pct)))))));

  const unquoted = pf.unquoted.length > 0 && h('div', {},
    h('h3', { class: 'sub-title' }, 'Sem cotação ao vivo (fora dos totais)'),
    h('div', { class: 'table-wrap' },
      h('table', { class: 'quotes positions' },
        h('thead', {}, h('tr', {}, ['Ativo', 'Qtd', 'Preço médio', 'Valor aplicado'].map((c) => h('th', { scope: 'col' }, c)))),
        h('tbody', {}, pf.unquoted.map((u) => h('tr', {},
          h('th', { scope: 'row' }, u.ticker),
          h('td', {}, num(u.quantity)),
          h('td', {}, brl(u.avg_price)),
          h('td', {}, brl(u.cost))))))));

  const dividends = pf.dividends.length > 0 && h('div', {},
    h('h3', { class: 'sub-title' }, 'Próximos proventos'),
    h('ul', { class: 'list compact' }, pf.dividends.map((d) =>
      h('li', { class: 'item' },
        h('span', { class: 'ticker' }, d.ticker),
        h('span', { class: 'muted' }, `${d.kind} · ${d.payment_date.split('-').reverse().join('/')}`),
        h('span', { class: 'amount' }, `≈ ${brl(d.estimated_total)}`)))));

  content.replaceChildren(h('div', { class: 'pf' },
    note && h('p', { class: 'panel-note' }, icon('alert'), note),
    h('div', {}, h('span', { class: 'label' }, 'Patrimônio (com cotação)'), h('strong', { class: 'big' }, brl(pf.total_value))),
    h('div', { class: 'pf-stats' },
      stat('Hoje', pf.day_change_value, pf.day_change_pct),
      stat('Sobre o preço médio', pf.result_value, pf.result_pct)),
    allocation,
    h('div', {}, h('h3', { class: 'sub-title' }, 'Posições'), table),
    unquoted,
    dividends,
    h('p', { class: 'disclaimer' }, 'Ativos em US$ convertidos pelo dólar do momento. Apenas uma descrição da carteira, não é recomendação de investimento.')));
}

// --- API pública -----------------------------------------------------------------

export async function openPrivate() {
  clear();
  dialog.showModal();
  let status;
  try {
    status = await getJSON('/api/private/status');
  } catch (err) {
    return showMessage(err.status === 404 ? 'Servidor desatualizado' : 'Erro', explain(err));
  }
  if (!status.enabled) {
    return showMessage('Aba desativada', status.message);
  }
  return status.unlocked ? showPortfolio() : showUnlockForm();
}

export const privateOpen = () => dialog.open;

dialog.querySelector('[data-action="private-lock"]').addEventListener('click', async () => {
  try {
    await postJSON('/api/private/lock', {});
  } catch { /* o importante é limpar a tela */ }
  showUnlockForm('Carteira bloqueada.');
});
dialog.querySelector('[data-action="private-close"]').addEventListener('click', close);
dialog.addEventListener('close', clear); // Esc também apaga os dados da tela

// Trocou de aba, minimizou ou bloqueou o Windows: some da tela
document.addEventListener('visibilitychange', () => {
  if (document.hidden) close();
});
