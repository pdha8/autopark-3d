// AutoPark 3D — orchestration : chargement, thème jour / nuit, sections, vidéos 3D,
// étiquettes synchronisées, simulation, réservation, visite guidée.

import '@fontsource/barlow-condensed/600.css';
import '@fontsource/barlow-condensed/700.css';
import '@fontsource/barlow/400.css';
import '@fontsource/barlow/500.css';
import '@fontsource/barlow/600.css';
import '@fontsource/jetbrains-mono/500.css';
import '@fontsource/jetbrains-mono/700.css';
import './styles/base.css';
import './styles/sections.css';
import './styles/panels.css';
import './styles/mobile.css';

import gsap from 'gsap';
import { store } from './core/store.js';
import { $, $$ } from './core/util.js';
import { ApiPanel } from './ui/api.js';
import { Booking, alertBanner, modalOpen, notify } from './ui/booking.js';
import { Dashboard } from './ui/dashboard.js';
import { Explorer } from './ui/explorer.js';
import { GateOverlay, HeroOverlay, RoofOverlay } from './ui/overlays.js';
import { Sections } from './ui/sections.js';
import { VideoScene } from './ui/videoScene.js';

const root = document.documentElement;
const params = new URLSearchParams(location.search);
const LABELS = ['Accueil', 'Entrée', 'Guidage', 'Niveaux', 'Dashboard', 'API'];
const THEME_KEY = 'autopark3d.theme';
// cadrage des scènes sur téléphone : point de la maquette à centrer, largeur visible (en unités)
const MOBILE_FOCUS = { hero: [760, 400, 890, 0.41], gate: [1010, 400, 560, 0.36], roof: [830, 330, 600, 0.36] };

let theme = params.get('theme') || localStorage.getItem(THEME_KEY) || 'night';
if (!['night', 'day'].includes(theme)) theme = 'night';
root.dataset.theme = theme;

const secEls = $$('.sec');
const scenes = new Map(); // index de section -> { scene, overlay, name }
secEls.forEach((el, i) => {
  if (!el.dataset.scene) return;
  const name = el.dataset.scene;
  const scene = new VideoScene($('.scene', el), name);
  const overlay = name === 'hero' ? new HeroOverlay(el) : name === 'gate' ? new GateOverlay(el) : new RoofOverlay(el);
  scenes.set(i, { scene, overlay, name, el });
});

let sections;
const booking = new Booking({ onGuide: (id) => guide(id) });
const explorer = new Explorer({ onReserve: (spot) => booking.open(spot), theme });
const dashboard = new Dashboard();
const api = new ApiPanel();
void dashboard;
void api;

// ------------------------------------------------------------ mise à l'échelle
function fit() {
  const w = window.innerWidth;
  const h = window.innerHeight;
  const mobile = w / h < 0.85;
  document.body.classList.toggle('is-mobile', mobile);
  const u = mobile ? w / 430 : Math.min(w / 1280, h / 776);
  root.style.setProperty('--u', `${u}px`);
  for (const { el, name } of scenes.values()) {
    const sc = $('.scene', el);
    if (!mobile) {
      sc.style.setProperty('--su', `${u}px`);
      sc.style.setProperty('--sx', '0px');
      sc.style.setProperty('--sy', '0px');
    } else {
      const [fx, fy, span, py] = MOBILE_FOCUS[name];
      const su = w / span;
      sc.style.setProperty('--su', `${su}px`);
      sc.style.setProperty('--sx', `${-(fx - 640) * su}px`);
      sc.style.setProperty('--sy', `${h * py - h / 2 - (fy - 388) * su}px`);
    }
  }
  sections?.resize(h);
}

// ------------------------------------------------------------ thème
function applyTheme(next, announce = true) {
  theme = next;
  root.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* stockage indisponible */
  }
  $('#theme-label').textContent = theme === 'night' ? 'Nuit' : 'Jour';
  $('#theme-btn').setAttribute('aria-label', theme === 'night' ? 'Passer en mode jour' : 'Passer en mode nuit');
  document.querySelector('meta[name=theme-color]').content = theme === 'night' ? '#0a0e1a' : '#e9edf2';
  const cur = scenes.get(sections ? sections.index : 0);
  cur?.scene.setVariant(theme);
  explorer.setTheme(theme);
  if (announce) notify(theme === 'night' ? 'Mode nuit activé' : 'Mode jour activé');
}

// ------------------------------------------------------------ sections
function reveal(i, delay = 0) {
  const els = $$('[data-reveal]', secEls[i]);
  gsap.killTweensOf(els);
  gsap.fromTo(els, { opacity: 0, y: 22 }, { opacity: 1, y: 0, duration: 0.8, stagger: 0.075, delay, ease: 'power3.out', overwrite: true });
}

function hide(i) {
  const els = $$('[data-reveal]', secEls[i]);
  gsap.killTweensOf(els);
  gsap.set(els, { opacity: 0, y: 22 });
}

async function activate(i) {
  const s = scenes.get(i);
  if (!s) return;
  if (s.scene.variant !== theme) await s.scene.setVariant(theme);
  s.scene.play();
  s.el.classList.add('is-live');
}

function onSection(i, prev) {
  $$('.nav__links a').forEach((a) => a.classList.toggle('is-active', +a.dataset.goto === i));
  $$('#dots button').forEach((b, k) => b.classList.toggle('is-active', k === i));
  document.body.dataset.section = i;
  activate(i);
  reveal(i, 0.42);
  void prev;
}

function onSectionDone(i, prev) {
  const p = scenes.get(prev);
  if (p && prev !== i) p.scene.pause();
  if (prev !== i) hide(prev);
  // précharge les vidéos des sections voisines
  for (const k of [i + 1, i - 1]) {
    const n = scenes.get(k);
    if (n && !n.scene.variant) n.scene.setVariant(theme);
  }
  scenes.get(i)?.scene.preloadOthers();
  history.replaceState(null, '', i ? `#${secEls[i].id}` : location.pathname + location.search);
}

function guide(spotId) {
  sections.goTo(3);
  explorer.focus(spotId);
}

// ------------------------------------------------------------ visite guidée
const TOUR = [
  [0, 'Vue d’ensemble : 240 places sur 4 niveaux', 9],
  [1, 'Entrée : la plaque est lue, la barrière se lève', 9],
  [2, 'Guidage : la place réservée s’allume en bleu', 9],
  [3, 'Niveaux : chaque place est cliquable', 7],
  [4, 'Dashboard : l’activité en temps réel', 6],
  [5, 'API : tout est intégrable', 6],
];
const tour = { on: false, step: 0, t: 0 };

function tourStep(k) {
  tour.step = k;
  tour.t = 0;
  $('#tour-caption').textContent = TOUR[k][1];
  if (sections.index !== TOUR[k][0]) sections.goTo(TOUR[k][0]);
}

function tourStart() {
  tour.on = true;
  $('#tourbar').hidden = false;
  tourStep(0);
}

function tourStop(back = false) {
  if (!tour.on) return;
  tour.on = false;
  $('#tourbar').hidden = true;
  if (back) sections.goTo(0);
}

function tourTick(dt) {
  if (!tour.on || sections.animating) return;
  tour.t += dt;
  const dur = TOUR[tour.step][2];
  $('#tour-progress').style.width = `${Math.min(100, (100 * tour.t) / dur)}%`;
  if (tour.t < dur) return;
  if (tour.step + 1 < TOUR.length) tourStep(tour.step + 1);
  else tourStop(true);
}

// ------------------------------------------------------------ démarrage
function bind() {
  $('#dots').innerHTML = LABELS.map((l, i) => `<button type="button" data-goto="${i}" aria-label="${l}"><span>${l}</span></button>`).join('');
  document.addEventListener('click', (e) => {
    const go = e.target.closest('[data-goto]');
    if (go) {
      e.preventDefault();
      tourStop();
      sections.goTo(+go.dataset.goto);
      return;
    }
    if (e.target.closest('[data-action="reserve-best"]')) booking.open();
    const smart = e.target.closest('.smart-spot, .chip[data-spot]');
    if (smart) guide(smart.dataset.spot);
    const level = e.target.closest('.tag--level[data-level]');
    if (level) {
      sections.goTo(3);
      explorer.setLevel(+level.dataset.level);
    }
  });
  $('#theme-btn').addEventListener('click', () => applyTheme(theme === 'night' ? 'day' : 'night'));
  $('#live-btn').addEventListener('click', (e) => {
    store.live = !store.live;
    e.currentTarget.classList.toggle('is-paused', !store.live);
    e.currentTarget.querySelector('span').textContent = store.live ? 'Live' : 'Pause';
    notify(store.live ? 'Simulation live reprise' : 'Simulation live en pause');
  });
  $('#tour-btn').addEventListener('click', tourStart);
  $('#tour-stop').addEventListener('click', () => tourStop());
  window.addEventListener('keydown', (e) => e.key === 'Escape' && tourStop());
  window.addEventListener('wheel', () => tourStop(), { passive: true });
  $('#mode-switch').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    const admin = b.dataset.mode === 'admin';
    document.body.classList.toggle('is-admin', admin);
    $$('#mode-switch button').forEach((x) => x.classList.toggle('is-active', x === b));
    notify(admin ? 'Mode administrateur' : 'Mode utilisateur');
  });
  $('#btn-sim-in').addEventListener('click', () => {
    const s = store.arrive();
    if (s) {
      notify(`Arrivée simulée · ${s.plate} → ${s.id}`);
      explorer.focus(s.id);
    } else notify('Parking complet', true);
  });
  $('#btn-sim-out').addEventListener('click', () => {
    const s = store.depart();
    if (s) {
      notify(`Sortie simulée · ${s.id} libérée`);
      explorer.focus(s.id);
    }
  });
  $('#btn-reset').addEventListener('click', () => {
    store.reset();
    explorer.select(null);
    notify('Système réinitialisé');
  });
  window.addEventListener('resize', fit);
}

// léger déplacement de la scène 3D avec le pointeur (effet de profondeur, ordinateur seulement)
const pointer = { x: 0, y: 0, cx: 0, cy: 0 };
window.addEventListener('pointermove', (e) => {
  pointer.x = e.clientX / window.innerWidth - 0.5;
  pointer.y = e.clientY / window.innerHeight - 0.5;
});

function parallax(dt, cur) {
  if (!cur || document.body.classList.contains('is-mobile')) return;
  const k = 1 - Math.exp(-dt * 3.2);
  pointer.cx += (pointer.x - pointer.cx) * k;
  pointer.cy += (pointer.y - pointer.cy) * k;
  const u = parseFloat(root.style.getPropertyValue('--u')) || 1;
  const sc = $('.scene', cur.el);
  sc.style.setProperty('--sx', `${(-pointer.cx * 14 * u).toFixed(2)}px`);
  sc.style.setProperty('--sy', `${(-pointer.cy * 9 * u).toFixed(2)}px`);
}

function loop() {
  let last = performance.now();
  let second = 0;
  const frame = (now) => {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    sections.update(dt);
    const cur = scenes.get(sections.index);
    if (cur && cur.scene.active) cur.overlay.update(cur.scene.time);
    parallax(dt, cur);
    store.tick(dt);
    explorer.update(dt, sections.index === 3 || sections.animating);
    tourTick(dt);
    second += dt;
    if (second >= 1) {
      second = 0;
      booking.tick();
      const c = store.counts();
      const rate = (c.occupied + c.reserved) / c.total;
      if (rate >= 0.9) alertBanner(`Parking presque plein — ${c.available} places restantes`, 'danger', 'full');
      else if (rate >= 0.8) alertBanner(`Parking à ${Math.round(rate * 100)} % — affluence élevée`, 'warn', 'high');
    }
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

async function boot() {
  bind();
  sections = new Sections({ container: $('#sections'), count: secEls.length, onStart: onSection, onComplete: onSectionDone, locked: modalOpen });
  fit();
  applyTheme(theme, false);
  secEls.forEach((_, i) => hide(i));

  const hero = scenes.get(0);
  hero.scene.setVariant(theme);
  const bar = $('#loader-bar');
  const pct = $('#loader-pct');
  const progress = (p) => {
    bar.style.width = `${Math.round(p * 100)}%`;
    pct.textContent = `${Math.round(p * 100)} %`;
  };
  // au plus 12 s d'attente : ensuite on démarre quand même (connexion lente, lecture bloquée)
  await Promise.race([hero.scene.ready(theme, progress), new Promise((r) => setTimeout(r, 12000))]);
  progress(1);

  const start = Math.max(0, Math.min(secEls.length - 1, +(params.get('section') ?? Math.max(0, secEls.findIndex((s) => `#${s.id}` === location.hash)))));
  sections.enabled = true;
  loop();
  $('#loader').classList.add('is-done');
  if (start > 0) sections.goTo(start, true);
  else {
    onSection(0, 0);
    onSectionDone(0, 0);
  }
  // mise au point : ?t=3.5 fige la vidéo de la section à cet instant
  if (params.has('t')) {
    const s = scenes.get(sections.index);
    if (s) {
      await s.scene.ready(theme);
      s.scene.pause();
      s.scene.active.currentTime = +params.get('t');
      s.scene.frameTime = null;
    }
  }
}

boot();
