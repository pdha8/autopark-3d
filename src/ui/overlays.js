// Étiquettes HTML calées sur les vidéos 3D : compteurs, état de la place suivie,
// bulle de lecture de plaque… Les instants viennent de la scène Blender
// (src/data/sync.json) : tout est synchronisé à l'image près avec la vidéo.

import sync from '../data/sync.json';
import { store, LOCKED } from '../core/store.js';
import { $, $$, BAY_LABEL, inLoop } from '../core/util.js';

const T = sync.loopTimes;
const LOOP = sync.loop;
const wrap = (t) => ((t % LOOP) + LOOP) % LOOP;

/** Pose chaque étiquette [data-anchor] à sa position dans la maquette. */
export function placeAnchors(section, view) {
  const anchors = sync.views[view].anchors;
  for (const el of $$('[data-anchor]', section)) {
    const p = anchors[el.dataset.anchor];
    if (!p) continue;
    el.style.setProperty('--ax', p[0]);
    el.style.setProperty('--ay', p[1]);
  }
  return anchors;
}

/** État de la place suivie (toit) à l'instant t de la boucle. */
export function bayState(t) {
  if (inLoop(t, T.parked, T.bay_clear)) return 'occupied';
  if (inLoop(t, T.bay_clear, T.reserved)) return 'available';
  return 'reserved';
}

function setChip(chip, label, state) {
  if (chip.dataset.state === state) return;
  chip.dataset.state = state;
  chip.style.setProperty('--c', `var(--${state})`);
  label.textContent = BAY_LABEL[state];
}

// ------------------------------------------------------------ accueil
export class HeroOverlay {
  constructor(section) {
    this.section = section;
    placeAnchors(section, 'hero');
    this.nums = { available: $('#stat-available'), occupied: $('#stat-occupied'), reserved: $('#stat-reserved'), total: $('#stat-total') };
    this.shown = {};
    this.barOcc = $('#bar-occ');
    this.barRes = $('#bar-res');
    this.chip = $('#hero-bay');
    this.chipState = $('#hero-bay-state');
    $('#hero-bay-id').textContent = sync.bay;
    this.toast = $('#hero-anpr');
    $('#hero-anpr-plate').textContent = sync.plate;
  }

  update(time) {
    const t = wrap(time);
    const state = bayState(t);
    // compteurs : état du parking + place suivie par la vidéo
    const c = store.counts();
    const base = store.byId.get(sync.bay).status;
    if (state !== base) {
      c[base]--;
      c[state]++;
    }
    for (const key of ['available', 'occupied', 'reserved', 'total']) {
      if (this.shown[key] === c[key]) continue;
      const el = this.nums[key];
      if (this.shown[key] !== undefined) {
        el.classList.remove('is-bump');
        void el.offsetWidth;
        el.classList.add('is-bump');
      }
      el.textContent = c[key];
      this.shown[key] = c[key];
    }
    this.barOcc.style.width = `${(100 * c.occupied) / c.total}%`;
    this.barRes.style.width = `${(100 * c.reserved) / c.total}%`;
    setChip(this.chip, this.chipState, state);
    this.toast.classList.toggle('is-on', inLoop(t, T.flash, wrap(T.flash + 2.7)));
  }
}

// ------------------------------------------------------------ entrée : lecture de plaque
export class GateOverlay {
  constructor(section) {
    this.section = section;
    const a = placeAnchors(section, 'gate');
    this.bubble = $('#gate-bubble');
    this.plate = $('#gate-plate');
    this.status = $('#gate-status');
    this.reticle = $('#gate-reticle');
    this.scan = $('#gate-scan');
    this.exit = $('#gate-exit');
    this.scan.setAttribute('viewBox', '0 0 1280 776');
    const line = this.scan.querySelector('line');
    line.setAttribute('x1', a.anpr[0]);
    line.setAttribute('y1', a.anpr[1] + 14);
    line.setAttribute('x2', a.plate[0]);
    line.setAttribute('y2', a.plate[1]);
    this._typed = -1;
  }

  update(time) {
    const t = wrap(time);
    const sinceFlash = wrap(t - T.flash); // secondes écoulées depuis le flash
    const bubbleOn = sinceFlash < wrap(T.in_close - T.flash) + 0.5;
    this.bubble.classList.toggle('is-on', bubbleOn);
    // plaque tapée caractère par caractère, juste après le flash
    const n = bubbleOn ? Math.min(sync.plate.length, Math.floor(sinceFlash / 0.05) + 1) : 0;
    if (n !== this._typed) {
      this._typed = n;
      const done = n >= sync.plate.length;
      this.plate.innerHTML = sync.plate.slice(0, n) + (done || !bubbleOn ? '' : '<span class="caret"></span>');
    }
    this.status.classList.toggle('is-on', bubbleOn && sinceFlash > 0.62);
    this.reticle.classList.toggle('is-on', inLoop(t, wrap(T.stop + 0.05), wrap(T.flash + 0.75)));
    this.scan.classList.toggle('is-on', inLoop(t, wrap(T.flash - 0.12), wrap(T.flash + 0.55)));
    this.exit.classList.toggle('is-on', inLoop(t, wrap(T.exit_gate - 0.4), wrap(T.out_close + 1.1)));
  }
}

// ------------------------------------------------------------ guidage : place réservée sur le toit
export class RoofOverlay {
  constructor(section) {
    this.section = section;
    const a = placeAnchors(section, 'roof');
    this.chip = $('#roof-bay');
    this.chipState = $('#roof-bay-state');
    $('#roof-bay-id').textContent = sync.bay;
    this.outline = $('#roof-outline');
    this.outline.setAttribute('viewBox', '0 0 1280 776');
    this.outline.querySelector('polygon').setAttribute('points', [a.bay0, a.bay1, a.bay2, a.bay3].map((p) => p.join(',')).join(' '));
    this.list = $('#smart-list');
    this.renderSmart();
    store.addEventListener('change', () => this.renderSmart());
    this.predict();
    setInterval(() => this.predict(), 60000);
  }

  update(time) {
    const state = bayState(wrap(time));
    setChip(this.chip, this.chipState, state);
    this.outline.style.setProperty('--c', `var(--${state})`);
    this.outline.style.opacity = state === 'occupied' ? 0 : 1;
  }

  renderSmart() {
    const top = store.suggestions(3);
    if (!top.length) {
      this.list.innerHTML = '<p class="predict__sub">Aucune place disponible</p>';
      return;
    }
    this.list.innerHTML = top
      .map(
        ({ spot, score }, i) => `<button class="smart-spot${i === 0 ? ' is-best' : ''}" type="button" data-spot="${spot.id}">
          <b>${spot.id}</b><em>${Math.round(score * 100)} pts</em>
          <small>Niveau P${spot.level} · ${store.walk(spot)} m de l'ascenseur</small>
        </button>`,
      )
      .join('');
  }

  /** Prévision d'occupation dans une heure (modèle simulé : profil horaire + week-end). */
  predict() {
    const hourly = [0.15, 0.12, 0.08, 0.06, 0.05, 0.1, 0.28, 0.52, 0.72, 0.81, 0.84, 0.82, 0.78, 0.75, 0.73, 0.76, 0.8, 0.82, 0.75, 0.62, 0.5, 0.38, 0.28, 0.2];
    const now = new Date();
    const weekend = [0, 6].includes(now.getDay()) ? 0.65 : 1;
    const at = (h) => Math.max(0.05, Math.min(0.98, hourly[(now.getHours() + h) % 24] * weekend));
    const p1 = Math.round(at(1) * 100);
    const p2 = Math.round(at(2) * 100);
    const color = p1 > 85 ? 'var(--occupied)' : p1 > 65 ? 'var(--selected)' : 'var(--available)';
    const trend = p1 > p2 ? 'En hausse' : p1 < p2 - 5 ? 'En baisse' : 'Stable';
    const box = $('#pred-value').closest('.predict');
    box.style.setProperty('--pc', color);
    $('#pred-value').textContent = `${p1} %`;
    $('#pred-bar').style.width = `${p1}%`;
    $('#pred-sub').textContent = `${trend} · dans 2 h : ${p2} %`;
  }
}

export { LOCKED };
