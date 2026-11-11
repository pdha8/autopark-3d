// Petits outils partagés.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
export const lerp = (a, b, t) => a + (b - a) * t;
export const smooth = (t) => {
  t = clamp(t);
  return t * t * (3 - 2 * t);
};
// défilement entre sections : départ et arrivée en douceur
export const EASE_SCROLL = (t) => (t < 0.5 ? 16 * t * t * t * t * t : 1 - Math.pow(-2 * t + 2, 5) / 2);

/** t est-il dans [a, b) sur une boucle (b peut être « avant » a) ? */
export const inLoop = (t, a, b) => (a <= b ? t >= a && t < b : t >= a || t < b);

export const euro = (v) => `${v.toFixed(2).replace('.', ',')} €`;
export const pad2 = (n) => String(n).padStart(2, '0');
export const hhmm = (ms) => {
  const d = new Date(ms);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
};
export const clock = (ms) => {
  const s = Math.max(0, Math.floor(Math.abs(ms) / 1000));
  const h = Math.floor(s / 3600);
  return `${ms < 0 ? '-' : ''}${h ? `${h}:` : ''}${pad2(Math.floor((s % 3600) / 60))}:${pad2(s % 60)}`;
};
export const duration = (ms) => {
  const m = Math.max(1, Math.round(ms / 60000));
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${pad2(m % 60)}`;
};

export const STATUS_LABEL = { available: 'Disponible', occupied: 'Occupé', reserved: 'Réservé', selected: 'Sélectionné' };
export const BAY_LABEL = { available: 'Libre', occupied: 'Occupée', reserved: 'Réservée' };
export const TYPE_LABEL = { std: 'Standard', ev: 'Recharge EV', pmr: 'PMR', family: 'Famille' };

export function download(name, text, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
