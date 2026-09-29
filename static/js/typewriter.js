// Efeito de digitação.
// O texto completo vai para leitores de tela de uma vez (span .sr-only);
// a versão "digitada" fica escondida deles, para não ser anunciada letra por letra.

import { h } from './dom.js';

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const running = new WeakMap(); // elemento -> token da digitação atual

/**
 * Digita `text` dentro de `el`. Uma nova chamada no mesmo elemento cancela a anterior.
 * @returns {Promise<void>} resolve quando termina (ou é cancelada)
 */
export function typeText(el, text, { cps = 55 } = {}) {
  const token = {};
  running.set(el, token);

  const visible = h('span', { 'aria-hidden': 'true' });
  const caret = h('span', { class: 'caret', 'aria-hidden': 'true' });
  el.replaceChildren(h('span', { class: 'sr-only' }, text), visible, caret);

  if (reduceMotion.matches) {
    visible.textContent = text;
    caret.remove();
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    const start = performance.now();
    function step(now) {
      if (running.get(el) !== token) return resolve();
      const count = Math.min(text.length, Math.floor(((now - start) / 1000) * cps));
      visible.textContent = text.slice(0, count);
      if (count < text.length) {
        requestAnimationFrame(step);
      } else {
        caret.remove();
        resolve();
      }
    }
    requestAnimationFrame(step);
  });
}
