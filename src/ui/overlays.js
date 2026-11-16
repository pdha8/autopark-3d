// Étiquettes HTML calées sur les vidéos 3D : compteurs, état de la place suivie,
// bulle de lecture de plaque… Les instants viennent de la scène Blender
// (src/data/sync.json) : tout est synchronisé à l'image près avec la vidéo.
// La vidéo montre toute une flotte : chaque entrée à la barrière a sa plaque, chaque
// place où un véhicule se gare ou repart fait bouger les compteurs.

import sync from '../data/sync.json';
import { store, LOCKED } from '../core/store.js';
import { $, $$, BAY_LABEL, inLoop } from '../core/util.js';

const LOOP = sync.loop;
const wrap = (t) => ((t % LOOP) + LOOP) % LOOP;
/** Secondes écoulées depuis l'instant t0 de la boucle. */
const since = (t, t0) => wrap(t - t0);
const HERO_BAY = sync.bays.find((b) => b.id === sync.bay);

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

/** État d'une place animée par la vidéo à l'instant t de la boucle. */
export function bayState(bay, t) {
  if (inLoop(t, bay.on, bay.off)) return 'occupied';
  if (bay.reserved !== undefined && inLoop(t, bay.reserved, bay.on)) return 'reserved';
  return 'available';
}

/** Dernière plaque lue à l'entrée, et depuis combien de secondes. */
function lastEntry(t) {
  let entry = sync.entries[0];
  let age = Infinity;
  for (const e of sync.entries) {
    const a = since(t, e.t);
    if (a < age) {
      age = a;
      entry = e;
    }
  }
  return { entry, age };
}

/** Prochaine plaque à lire, et dans combien de secondes. */
function nextEntry(t) {
  let entry = sync.entries[0];
  let wait = Infinity;
  for (const e of sync.entries) {
    const w = since(e.t, t);
    if (w < wait) {
      wait = w;
      entry = e;
    }
  }
  return { entry, wait };
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
    this.plate = $('#hero-anpr-plate');
    this._plate = null;
  }

  update(time) {
    const t = wrap(time);
    // compteurs : état du parking + toutes les places où la vidéo montre un véhicule garé
    const c = store.counts();
    for (const bay of sync.bays) {
      const base = store.byId.get(bay.id).status;
      const state = bayState(bay, t);
      if (state !== base) {
        c[base]--;
        c[state]++;
      }
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
    setChip(this.chip, this.chipState, bayState(HERO_BAY, t));
    // plaque lue à l'entrée : celle du véhicule qui passe la barrière
    const { entry, age } = lastEntry(t);
    const on = age < 2.6;
    if (on && entry.plate !== this._plate) {
      this._plate = entry.plate;
      this.plate.textContent = entry.plate;
    }
    this.toast.classList.toggle('is-on', on);
  }
}

// ------------------------------------------------------------ entrée : lecture de plaque
export class GateOverlay {
  constructor(section) {
    this.section = section;
    this.anchors = placeAnchors(section, 'gate');
    this.bubble = $('#gate-bubble');
    this.plate = $('#gate-plate');
    this.status = $('#gate-status');
    this.reticle = $('#gate-reticle');
    this.scan = $('#gate-scan');
    this.exit = $('#gate-exit');
    this.scan.setAttribute('viewBox', '0 0 1280 776');
    this.line = this.scan.querySelector('line');
    this.line.setAttribute('x1', this.anchors.anpr[0]);
    this.line.setAttribute('y1', this.anchors.anpr[1] + 14);
    this._typed = -1;
    this._read = null;
    this._aim = null;
  }

  /** Vise la plaque d'un véhicule (réticule et trait de lecture). */
  aim(entry) {
    if (entry === this._aim) return;
    this._aim = entry;
    this.reticle.style.setProperty('--ax', entry.at[0]);
    this.reticle.style.setProperty('--ay', entry.at[1]);
    this.line.setAttribute('x2', entry.at[0]);
    this.line.setAttribute('y2', entry.at[1]);
  }

  update(time) {
    const t = wrap(time);
    const { entry, age } = lastEntry(t); // plaque en cours d'affichage
    const { entry: next, wait } = nextEntry(t); // prochain véhicule à lire
    // la bulle reste jusqu'à ce que le véhicule ait passé la barrière
    const bubbleOn = age < since(entry.close, entry.t) + 0.5;
    this.bubble.classList.toggle('is-on', bubbleOn);
    if (entry !== this._read) {
      this._read = entry;
      this._typed = -1;
    }
    // plaque tapée caractère par caractère, juste après le flash
    const n = bubbleOn ? Math.min(entry.plate.length, Math.floor(age / 0.05) + 1) : 0;
    if (n !== this._typed) {
      this._typed = n;
      const done = n >= entry.plate.length;
      this.plate.innerHTML = entry.plate.slice(0, n) + (done || !bubbleOn ? '' : '<span class="caret"></span>');
    }
    this.status.classList.toggle('is-on', bubbleOn && age > 0.62);
    // réticule : sur la plaque dès que le véhicule s'arrête (ou juste avant la lecture s'il passe au pas)
    const lead = next.stop === null ? 0.5 : since(next.t, next.stop) - 0.05;
    const aiming = wait < lead;
    this.aim(aiming ? next : entry);
    this.reticle.classList.toggle('is-on', aiming || age < 0.75);
    this.scan.classList.toggle('is-on', wait < 0.12 || age < 0.55);
    this.exit.classList.toggle('is-on', sync.exits.some((e) => inLoop(t, wrap(e.gate - 0.4), wrap(e.close + 1.1))));
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
    const state = bayState(HERO_BAY, wrap(time));
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
