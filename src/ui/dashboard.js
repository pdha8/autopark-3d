// Tableau de bord : indicateurs et graphiques (SVG), alimentés par l'état du parking.
// Les courbes horaires sont simulées (profil type d'une journée), comme dans le prototype.

import { store } from '../core/store.js';
import { $, euro } from '../core/util.js';

const NS = 'http://www.w3.org/2000/svg';
const HOURLY = [0.15, 0.12, 0.08, 0.06, 0.05, 0.1, 0.28, 0.52, 0.72, 0.81, 0.84, 0.82, 0.78, 0.75, 0.73, 0.76, 0.8, 0.82, 0.75, 0.62, 0.5, 0.38, 0.28, 0.2];
const TYPES = [
  ['std', 'Standard', 'var(--reserved)'],
  ['ev', 'EV', 'var(--ev)'],
  ['pmr', 'PMR', 'var(--pmr)'],
  ['family', 'Famille', 'var(--family)'],
];

const el = (tag, attrs = {}, text = null) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== null) n.textContent = text;
  return n;
};

/** Nombre pseudo-aléatoire stable (même graphique à chaque affichage de la journée). */
function seeded(i) {
  const x = Math.sin((i + 1) * 12.9898 + new Date().getDate() * 78.233) * 43758.5453;
  return x - Math.floor(x);
}

export class Dashboard {
  constructor() {
    this.occ = $('#chart-occupancy');
    this.flow = $('#chart-flow');
    $('#dash-date').textContent = new Date().toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    store.addEventListener('change', () => this.render());
    store.addEventListener('reservation', () => this.render());
    this.render();
  }

  render() {
    const c = store.counts();
    const rate = (c.occupied + c.reserved) / c.total;
    const hour = new Date().getHours();
    const series = HOURLY.map((v, h) => Math.max(0.03, Math.min(0.97, v + (seeded(h) - 0.5) * 0.06)));
    const peak = series.indexOf(Math.max(...series));
    $('#kpi-rate').textContent = `${Math.round(rate * 100)} %`;
    $('#kpi-avail').textContent = c.available;
    $('#kpi-revenue').textContent = euro(store.revenue);
    $('#kpi-peak').textContent = `${peak} h`;
    // cartes « administration » de l'explorateur
    $('#adm-rate').textContent = `${Math.round(rate * 100)} %`;
    $('#adm-revenue').textContent = euro(412.5 + store.revenue);
    $('#adm-active').textContent = c.reserved;
    this._occupancy(series, hour);
    this._flow(hour);
    this._types();
    this._levels();
  }

  _occupancy(series, hour) {
    const W = 760;
    const H = 220;
    const L = 34;
    const R = 10;
    const T = 12;
    const B = 26;
    const x = (h) => L + ((W - L - R) * h) / 23;
    const y = (v) => T + (H - T - B) * (1 - v);
    const svg = this.occ;
    svg.replaceChildren();
    const defs = el('defs');
    const grad = el('linearGradient', { id: 'occ-fill', x1: 0, y1: 0, x2: 0, y2: 1 });
    grad.append(el('stop', { offset: '0%', 'stop-color': 'var(--reserved)', 'stop-opacity': 0.42 }), el('stop', { offset: '100%', 'stop-color': 'var(--reserved)', 'stop-opacity': 0 }));
    defs.append(grad);
    svg.append(defs);
    for (const v of [0, 0.25, 0.5, 0.75, 1]) {
      svg.append(el('line', { class: 'grid', x1: L, x2: W - R, y1: y(v), y2: y(v) }));
      svg.append(el('text', { x: L - 6, y: y(v) + 3, 'text-anchor': 'end' }, `${v * 100}%`));
    }
    for (let h = 0; h < 24; h += 3) svg.append(el('text', { x: x(h), y: H - 8, 'text-anchor': 'middle' }, `${h}h`));
    // courbe lissée (Catmull-Rom -> Bézier)
    const pts = series.map((v, h) => [x(h), y(v)]);
    let d = `M${pts[0][0]},${pts[0][1]}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[Math.max(0, i - 1)];
      const p1 = pts[i];
      const p2 = pts[i + 1];
      const p3 = pts[Math.min(pts.length - 1, i + 2)];
      d += ` C${p1[0] + (p2[0] - p0[0]) / 6},${p1[1] + (p2[1] - p0[1]) / 6} ${p2[0] - (p3[0] - p1[0]) / 6},${p2[1] - (p3[1] - p1[1]) / 6} ${p2[0]},${p2[1]}`;
    }
    svg.append(el('path', { d: `${d} L${x(23)},${y(0)} L${x(0)},${y(0)} Z`, fill: 'url(#occ-fill)' }));
    svg.append(el('path', { d, fill: 'none', stroke: 'var(--reserved)', 'stroke-width': 2.4, 'stroke-linecap': 'round', 'vector-effect': 'non-scaling-stroke' }));
    // maintenant
    svg.append(el('line', { x1: x(hour), x2: x(hour), y1: T, y2: y(0), stroke: 'var(--selected)', 'stroke-width': 1, 'stroke-dasharray': '3 4', 'vector-effect': 'non-scaling-stroke' }));
    svg.append(el('circle', { cx: x(hour), cy: y(series[hour]), r: 4.5, fill: 'var(--selected)' }));
    svg.append(el('text', { x: Math.min(W - 70, x(hour) + 8), y: T + 10, style: 'fill: var(--selected)' }, 'maintenant'));
  }

  _flow(hour) {
    const W = 520;
    const H = 190;
    const L = 8;
    const T = 10;
    const B = 24;
    const svg = this.flow;
    svg.replaceChildren();
    const n = 24;
    const bw = (W - 2 * L) / n;
    const arrivals = [];
    const departures = [];
    for (let i = 0; i < n; i++) {
      const h = (hour - (n - 1) + i + 48) % 24;
      const delta = HOURLY[h] - HOURLY[(h + 23) % 24];
      arrivals.push(Math.round(8 + Math.max(0, delta) * 150 + seeded(i + 40) * 6));
      departures.push(Math.round(8 + Math.max(0, -delta) * 150 + seeded(i + 80) * 6));
    }
    arrivals[n - 1] += store.flow.in;
    departures[n - 1] += store.flow.out;
    const max = Math.max(...arrivals, ...departures, 1);
    const mid = T + (H - T - B) / 2;
    const scale = (H - T - B) / 2 / max;
    svg.append(el('line', { class: 'grid', x1: L, x2: W - L, y1: mid, y2: mid }));
    for (let i = 0; i < n; i++) {
      const x = L + i * bw + bw * 0.18;
      const w = bw * 0.64;
      svg.append(el('rect', { x, y: mid - arrivals[i] * scale, width: w, height: arrivals[i] * scale, rx: 2, fill: 'var(--occupied)', opacity: i === n - 1 ? 1 : 0.72 }));
      svg.append(el('rect', { x, y: mid, width: w, height: departures[i] * scale, rx: 2, fill: 'var(--available)', opacity: i === n - 1 ? 1 : 0.72 }));
      if (i % 4 === 3) svg.append(el('text', { x: x + w / 2, y: H - 7, 'text-anchor': 'middle' }, `${(hour - (n - 1) + i + 48) % 24}h`));
    }
    svg.append(el('text', { x: L + 2, y: T + 8 }, 'arrivées'));
    svg.append(el('text', { x: L + 2, y: H - B - 4 }, 'départs'));
  }

  _types() {
    const data = store.byType();
    $('#chart-types').innerHTML = TYPES.map(([key, label, color]) => {
      const t = data[key] || { total: 0, used: 0 };
      const max = Math.max(...Object.values(data).map((o) => o.total));
      const scale = key === 'std' ? 100 : Math.max(22, (100 * t.total) / max * 4);
      return `<div class="types__row"><span>${label}</span><div class="types__track" style="--c:${color}"><i style="width:${(scale * t.used) / Math.max(1, t.total)}%"></i><i style="width:${(scale * (t.total - t.used)) / Math.max(1, t.total)}%"></i></div><b>${t.used}/${t.total}</b></div>`;
    }).join('');
  }

  _levels() {
    $('#chart-levels').innerHTML = [0, 1, 2, 3]
      .map((lv) => {
        const c = store.counts(lv);
        const pct = (v) => `${(100 * v) / c.total}%`;
        return `<div class="bylevel__col"><b>${Math.round((100 * (c.occupied + c.reserved)) / c.total)} %</b><div class="bylevel__stack"><i style="--c:var(--occupied);height:${pct(c.occupied)}"></i><i style="--c:var(--reserved);height:${pct(c.reserved)}"></i></div><span>P${lv}</span></div>`;
      })
      .join('');
  }
}
