// Formatação pt-BR para a interface.

const brlFormat = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const numFormat = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 });
const HOUR = 3_600_000;

const brl4Format = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 4 });
const usdFormat = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'USD' });

export const brl = (v) => brlFormat.format(v);
/** Câmbio com 4 casas, como nas mesas de câmbio: "R$ 5,2044" */
export const brl4 = (v) => brl4Format.format(v);
/** "US$ 702,46" */
export const usd = (v) => usdFormat.format(v);
export const num = (v) => numFormat.format(v);

export function signedBrl(v) {
  const sign = v > 0 ? '+' : v < 0 ? '−' : '';
  return sign + brlFormat.format(Math.abs(v));
}

export function pct(v, signed = true) {
  const sign = signed && v > 0 ? '+' : v < 0 ? '−' : '';
  return `${sign}${Math.abs(v).toFixed(2).replace('.', ',')}%`;
}

export const trendClass = (v) => (v > 0 ? 'pos' : v < 0 ? 'neg' : '');

export const time = (d) => d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());

export function dayDiff(d, now = new Date()) {
  return Math.round((startOfDay(d) - startOfDay(now)) / (24 * HOUR));
}

export function shortDate(d) {
  const weekday = d.toLocaleDateString('pt-BR', { weekday: 'short' }).replace('.', '');
  const date = d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
  return `${weekday} ${date}`;
}

export function dayLabel(d, now = new Date()) {
  const diff = dayDiff(d, now);
  if (diff === 0) return `Hoje · ${shortDate(d)}`;
  if (diff === 1) return `Amanhã · ${shortDate(d)}`;
  return shortDate(d);
}

/** "há 12 min", "há 3 h", "ontem", "25/09" */
export function ago(d, now = new Date()) {
  const minutes = Math.floor((now - d) / 60_000);
  if (minutes < 1) return 'agora';
  if (minutes < 60) return `há ${minutes} min`;
  if (dayDiff(d, now) === 0) return `há ${Math.floor(minutes / 60)} h`;
  if (dayDiff(d, now) === -1) return 'ontem';
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
}

/** Horas até o prazo: "em 45 min", "em 20 h", "em 3 d 4 h", "atrasada há 2 h" */
export function timeLeft(hours) {
  if (hours <= 0) {
    const late = Math.abs(hours);
    return late < 24 ? `atrasada há ${Math.max(1, Math.floor(late))} h` : `atrasada há ${Math.floor(late / 24)} d`;
  }
  if (hours < 1) return `em ${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 24) return `em ${Math.floor(hours)} h`;
  const days = Math.floor(hours / 24);
  const rest = Math.floor(hours % 24);
  return rest ? `em ${days} d ${rest} h` : `em ${days} d`;
}

export const hoursUntil = (d, now = new Date()) => (d - now) / HOUR;
