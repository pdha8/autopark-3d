// Explorateur des niveaux : plan 3D de chaque niveau (rendu Blender), où chaque
// place est cliquable. L'image de fond (niveau vide) et les voitures (une vignette
// par place, découpée dans le rendu « niveau plein ») sont recomposées dans un
// <canvas> selon l'état en direct du parking.

import { store, LOCKED } from '../core/store.js';
import { $, $$, STATUS_LABEL, TYPE_LABEL, hhmm, keyTabs, markTabs } from '../core/util.js';

const BASE = `${import.meta.env.BASE_URL}img/levels/`;
const FEED_LABEL = { arrival: 'Arrivée', departure: 'Départ', booking: 'Réservation' };
const FEED_COLOR = { arrival: 'var(--occupied)', departure: 'var(--available)', booking: 'var(--reserved)' };

function loadImage(src) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

export class Explorer {
  constructor({ onReserve, theme }) {
    this.onReserve = onReserve;
    this.theme = theme;
    this.level = 3;
    this.selected = null;
    this.hover = null;
    this.highlight = null; // place mise en avant (recherche, guidage)
    this.meta = null;
    this.images = {};
    this.fade = new Map(); // id -> opacité de la voiture (0 à 1), animée
    this.dirty = true;
    this.canvas = $('#level-canvas');
    this.ctx = this.canvas.getContext('2d');
    this.tip = $('#tip');

    $('#levels').addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (b) this.setLevel(+b.dataset.level);
    });
    this.canvas.addEventListener('pointermove', (e) => this._move(e));
    this.canvas.addEventListener('pointerleave', () => this._setHover(null));
    this.canvas.addEventListener('click', (e) => {
      const s = this._pick(e);
      if (s) this.select(s);
    });
    // au clavier : flèches de place en place, Entrée ou Espace pour sélectionner
    this.cursor = null;
    keyTabs($('#levels'));
    this.canvas.addEventListener('keydown', (e) => this._key(e));
    this.canvas.addEventListener('focus', () => {
      if (!this.meta) return;
      const spots = this.meta.levels[this.level].spots;
      const m = spots.find((o) => o.id === this.cursor) || spots.find((o) => o.id === this.selected?.id) || spots[0];
      this._setCursor(m);
    });
    this.canvas.addEventListener('blur', () => this._setHover(null));
    $('#reserve-btn').addEventListener('click', () => this.selected && this.onReserve(this.selected));
    $('#search-input').addEventListener('input', (e) => this._search(e.target.value));
    $('#search-results').addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (b) this.focus(b.dataset.spot);
    });
    store.addEventListener('change', (e) => this._onChange(e.detail));
    this._load();
    this._stats();
    this._feed();
  }

  async _load() {
    try {
      this.meta = await (await fetch(`${BASE}levels.json`)).json();
    } catch {
      this.meta = null;
    }
    if (!this.meta) {
      this._placeholder();
      return;
    }
    this.canvas.width = this.meta.width;
    this.canvas.height = this.meta.height;
    for (const s of store.spots) this.fade.set(s.id, s.status === 'occupied' ? 1 : 0);
    await this._images(this.level, this.theme);
    this.dirty = true;
    // les autres niveaux se chargent ensuite, en tâche de fond
    for (let lv = 0; lv < this.meta.levels.length; lv++) if (lv !== this.level) this._images(lv, this.theme);
  }

  async _images(level, theme) {
    const key = `${level}_${theme}`;
    if (!this.images[key]) {
      this.images[key] = Promise.all([loadImage(`${BASE}P${level}_${theme}.webp`), loadImage(`${BASE}P${level}_${theme}_cars.webp`)]).then(([base, cars]) => {
        this.images[key] = { base, cars };
        this.dirty = true;
        return this.images[key];
      });
    }
    return this.images[key];
  }

  setTheme(theme) {
    this.theme = theme;
    if (this.meta) this._images(this.level, theme);
    this.dirty = true;
  }

  setLevel(level) {
    this.level = level;
    $$('#levels button').forEach((b) => b.classList.toggle('is-active', +b.dataset.level === level));
    const tab = $(`#lvl-tab-${level}`);
    if (tab) {
      markTabs($('#levels'), tab);
      $('#level-map').setAttribute('aria-labelledby', tab.id);
    }
    this.canvas.setAttribute('aria-label', `Plan du niveau P${level}`);
    this.cursor = null;
    if (this.meta) this._images(level, this.theme);
    this._setHover(null);
    this._stats();
    this.dirty = true;
  }

  /** Affiche le niveau d'une place et la met en avant (recherche, « me guider »). */
  focus(id) {
    const s = store.byId.get(id);
    if (!s) return;
    this.setLevel(s.level);
    this.highlight = { id, t: performance.now() };
    this.select(s);
  }

  select(s) {
    this.selected = s;
    this._card();
    this.dirty = true;
  }

  // ------------------------------------------------------------ interface
  _card() {
    const s = this.selected;
    $('#spot-empty').hidden = !!s;
    $('#spot-body').hidden = !s;
    if (!s) return;
    const mine = s.mine;
    const locked = LOCKED.has(s.id);
    $('#spot-id').textContent = s.id;
    const badge = $('#spot-status');
    badge.textContent = mine ? 'Votre place' : STATUS_LABEL[s.status];
    badge.style.setProperty('--c', mine ? 'var(--selected-ink)' : `var(--${s.status})`);
    $('#spot-level').textContent = `P${s.level}${s.level === 3 ? ' · toit' : ''}`;
    $('#spot-type').textContent = TYPE_LABEL[s.type];
    $('#spot-plate').textContent = s.plate || '—';
    const score = store.score(s);
    $('#spot-score').textContent = score >= 0 ? `${Math.round(score * 100)} pts · ${store.walk(s)} m` : '—';
    const btn = $('#reserve-btn');
    btn.disabled = s.status !== 'available' || locked || !!store.active;
    $('#spot-note').textContent = locked
      ? 'Place suivie en direct dans les vidéos : elle ne peut pas être réservée ici.'
      : mine
        ? 'Votre réservation est en cours sur cette place.'
        : s.status === 'available'
          ? store.active
            ? 'Vous avez déjà une réservation en cours.'
            : 'Tarif : 3,50 € par heure, paiement simulé.'
          : s.status === 'reserved'
            ? 'Place réservée par un autre usager.'
            : 'Place occupée.';
  }

  _stats() {
    const c = store.counts(this.level);
    $('#lvl-name').textContent = `P${this.level}`;
    $('#lvl-available').textContent = c.available;
    $('#lvl-occupied').textContent = c.occupied;
    $('#lvl-reserved').textContent = c.reserved;
  }

  _feed() {
    $('#feed').innerHTML = store.feed
      .slice(0, 5)
      .map((f) => `<li><i class="dot" style="--c:${FEED_COLOR[f.type]}"></i><span>${FEED_LABEL[f.type]} <b>${f.id}</b></span><time>${hhmm(f.time)}</time></li>`)
      .join('');
  }

  _search(q) {
    const hits = store.search(q);
    $('#search-results').innerHTML = hits.map((s) => `<button type="button" data-spot="${s.id}"><b>${s.id}</b><span>${s.plate || STATUS_LABEL[s.status]}</span></button>`).join('');
  }

  _onChange({ spot }) {
    this._stats();
    this._feed();
    if (this.selected && (!spot || spot.id === this.selected.id)) this._card();
    if (!spot) for (const s of store.spots) this.fade.set(s.id, s.status === 'occupied' ? 1 : 0);
    this.dirty = true;
  }

  // ------------------------------------------------------------ clavier
  _centroid(m) {
    const n = m.poly.length;
    return [m.poly.reduce((a, p) => a + p[0], 0) / n, m.poly.reduce((a, p) => a + p[1], 0) / n];
  }

  _key(e) {
    if (!this.meta) return;
    const dirs = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] };
    if (e.key in dirs) {
      this._step(...dirs[e.key]);
    } else if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
      const s = this.cursor && store.byId.get(this.cursor);
      if (!s) return;
      this.select(s);
      const can = !$('#reserve-btn').disabled;
      this._say(`${s.id} sélectionnée.${can ? ' Tabulation pour la réserver.' : ''}`);
    } else if (e.key === 'Home' || e.key === 'End') {
      const spots = this.meta.levels[this.level].spots;
      this._setCursor(e.key === 'Home' ? spots[0] : spots[spots.length - 1]);
    } else return;
    e.preventDefault();
    e.stopPropagation(); // ces touches changent aussi de section : pas ici
  }

  /** Place la plus proche dans la direction (dx, dy) : d'abord dans l'axe, puis la plus alignée. */
  _step(dx, dy) {
    const spots = this.meta.levels[this.level].spots;
    const cur = spots.find((m) => m.id === this.cursor);
    if (!cur) return this._setCursor(spots[0]);
    const [cx, cy] = this._centroid(cur);
    let best = null;
    let score = Infinity;
    for (const m of spots) {
      if (m === cur) continue;
      const [x, y] = this._centroid(m);
      const along = (x - cx) * dx + (y - cy) * dy;
      if (along <= 4) continue;
      const across = Math.abs((x - cx) * dy - (y - cy) * dx);
      const sc = along + across * 2.5;
      if (sc < score) {
        score = sc;
        best = m;
      }
    }
    if (best) this._setCursor(best);
  }

  _setCursor(m) {
    if (!m) return;
    this.cursor = m.id;
    const s = store.byId.get(m.id);
    this._setHover(s);
    // la bulle d'information se place sur la place choisie
    const r = this.canvas.getBoundingClientRect();
    const host = this.canvas.parentElement.getBoundingClientRect();
    const [x, y] = this._centroid(m);
    this.tip.style.left = `${r.left - host.left + (x / this.canvas.width) * r.width}px`;
    this.tip.style.top = `${r.top - host.top + (y / this.canvas.height) * r.height}px`;
    const type = s.type !== 'std' ? `, ${TYPE_LABEL[s.type]}` : '';
    this._say(`${s.id}, ${s.mine ? 'votre place' : STATUS_LABEL[s.status].toLowerCase()}${type}${s.plate ? `, plaque ${s.plate}` : ''}`);
  }

  _say(text) {
    $('#plan-live').textContent = text;
  }

  // ------------------------------------------------------------ pointeur
  _point(e) {
    const r = this.canvas.getBoundingClientRect();
    return [((e.clientX - r.left) / r.width) * this.canvas.width, ((e.clientY - r.top) / r.height) * this.canvas.height];
  }

  _pick(e) {
    if (!this.meta) return null;
    const [x, y] = this._point(e);
    const spots = this.meta.levels[this.level].spots;
    // d'abord les voitures (elles dépassent de leur place), de l'avant vers l'arrière
    for (let i = spots.length - 1; i >= 0; i--) {
      const m = spots[i];
      const s = store.byId.get(m.id);
      if (s.status === 'occupied' && m.sprite) {
        const [, , w, h, dx, dy] = m.sprite;
        if (x > dx + w * 0.12 && x < dx + w * 0.88 && y > dy + h * 0.1 && y < dy + h * 0.9) return s;
      }
    }
    for (const m of spots) if (inside(m.poly, x, y)) return store.byId.get(m.id);
    return null;
  }

  _move(e) {
    const s = this._pick(e);
    this._setHover(s);
    if (!s) return;
    const r = this.canvas.getBoundingClientRect();
    const host = this.canvas.parentElement.getBoundingClientRect();
    this.tip.style.left = `${e.clientX - host.left}px`;
    this.tip.style.top = `${e.clientY - host.top}px`;
    void r;
  }

  _setHover(s) {
    if (s === this.hover) return;
    this.hover = s;
    this.canvas.style.cursor = s ? 'pointer' : 'default';
    this.tip.classList.toggle('is-on', !!s);
    if (s) {
      $('#tip-id').textContent = s.id + (s.type !== 'std' ? ` · ${TYPE_LABEL[s.type]}` : '');
      const st = $('#tip-status');
      st.textContent = s.mine ? 'Votre place' : STATUS_LABEL[s.status];
      st.style.setProperty('--c', s.mine ? 'var(--selected-ink)' : `var(--${s.status})`);
      $('#tip-plate').textContent = s.plate || '';
    }
    this.dirty = true;
  }

  // ------------------------------------------------------------ dessin
  update(dt, visible) {
    if (!this.meta || !visible) return;
    // fondu des voitures qui arrivent / repartent
    for (const m of this.meta.levels[this.level].spots) {
      const s = store.byId.get(m.id);
      const target = s.status === 'occupied' ? 1 : 0;
      const cur = this.fade.get(m.id) ?? target;
      if (cur !== target) {
        const next = cur + Math.sign(target - cur) * Math.min(Math.abs(target - cur), dt / 0.45);
        this.fade.set(m.id, next);
        this.dirty = true;
      }
    }
    if (this.highlight && performance.now() - this.highlight.t < 4000) this.dirty = true;
    else this.highlight = null;
    if (this.selected || this.hover) this.dirty = true; // contour animé
    if (!this.dirty) return;
    this.dirty = false;
    this._draw();
  }

  _draw() {
    const { ctx, canvas } = this;
    const lv = this.meta.levels[this.level];
    const img = this.images[`${this.level}_${this.theme}`];
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!img || img.then || !img.base) return;
    ctx.drawImage(img.base, 0, 0, canvas.width, canvas.height);
    const css = getComputedStyle(document.documentElement);
    const color = (name) => css.getPropertyValue(`--${name}`).trim();
    const night = this.theme === 'night';
    const now = performance.now();

    // boucles lumineuses des places
    ctx.lineJoin = 'round';
    for (const m of lv.spots) {
      const s = store.byId.get(m.id);
      const sel = this.selected?.id === m.id || s.mine;
      const key = sel ? 'selected' : s.status === 'available' && s.type !== 'std' ? s.type : s.status;
      const c = color(key);
      const hot = this.hover?.id === m.id || sel || this.highlight?.id === m.id;
      path(ctx, m.loop);
      if (hot) {
        ctx.fillStyle = withAlpha(c, 0.16 + (sel ? 0.1 * Math.sin(now / 260) + 0.1 : 0));
        ctx.fill();
      }
      ctx.shadowColor = c;
      ctx.shadowBlur = night ? 14 : 0;
      ctx.strokeStyle = c;
      ctx.lineWidth = hot ? 4.2 : night ? 2.6 : 2.9;
      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    // voitures : de l'arrière vers l'avant
    if (img.cars) {
      for (const m of lv.spots) {
        const a = this.fade.get(m.id) ?? 0;
        if (a <= 0.004 || !m.sprite) continue;
        const [sx, sy, w, h, dx, dy] = m.sprite;
        ctx.globalAlpha = a;
        ctx.drawImage(img.cars, sx, sy, w, h, dx, dy - (1 - a) * 10, w, h);
      }
      ctx.globalAlpha = 1;
    }

    // repère de la place mise en avant (recherche, guidage)
    if (this.highlight) {
      const m = lv.spots.find((o) => o.id === this.highlight.id);
      if (m) {
        const cx = m.poly.reduce((a, p) => a + p[0], 0) / 4;
        const cy = m.poly.reduce((a, p) => a + p[1], 0) / 4;
        const k = ((now - this.highlight.t) % 1200) / 1200;
        ctx.strokeStyle = withAlpha(color('selected'), 1 - k);
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.ellipse(cx, cy, 30 + 90 * k, (30 + 90 * k) * 0.55, 0, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
  }

  _placeholder() {
    const { ctx, canvas } = this;
    ctx.fillStyle = 'rgba(120,190,255,0.06)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = 'rgba(160,190,230,0.6)';
    ctx.font = '600 30px Barlow, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Plan des niveaux en cours de rendu…', canvas.width / 2, canvas.height / 2);
  }
}

function path(ctx, pts) {
  ctx.beginPath();
  pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.closePath();
}

function inside(poly, x, y) {
  let inC = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inC = !inC;
  }
  return inC;
}

function withAlpha(c, a) {
  a = Math.max(0, Math.min(1, a));
  if (c.startsWith('#')) {
    const n = c.length === 4 ? c.slice(1).replace(/./g, '$&$&') : c.slice(1);
    return `rgba(${parseInt(n.slice(0, 2), 16)},${parseInt(n.slice(2, 4), 16)},${parseInt(n.slice(4, 6), 16)},${a})`;
  }
  return c;
}
