// API système (simulée) : chaque endpoint répond à partir de l'état du parking
// dans le navigateur. Rien n'est envoyé sur le réseau.

import { store, randomPlate, RATE } from '../core/store.js';
import { $, $$, download, pad2 } from '../core/util.js';
import { notify } from './booking.js';

const ENDPOINTS = [
  { id: 'spots', method: 'GET', url: '/spots', desc: 'Toutes les places avec statut, niveau, type, plaque' },
  { id: 'available', method: 'GET', url: '/spots?status=available', desc: 'Filtre les places disponibles uniquement' },
  { id: 'reserve', method: 'POST', url: '/reservations', desc: 'Crée une réservation · Body : { spotId, plate, durationH }' },
  { id: 'cancel', method: 'DEL', url: '/reservations/:id', desc: 'Annule une réservation et libère la place' },
  { id: 'stats', method: 'GET', url: '/stats', desc: "Statistiques globales : taux d'occupation, CA, flux" },
  { id: 'anpr', method: 'POST', url: '/anpr/scan', desc: "Soumet une plaque à l'ANPR · Body : { plate, cameraId }" },
];
const COLORS = { GET: 'var(--reserved)', POST: 'var(--available)', DEL: 'var(--occupied)', PUT: 'var(--selected)' };

const view = (s) => ({ id: s.id, level: s.level, type: s.type, status: s.status, plate: s.plate });

function stats() {
  const c = store.counts();
  return {
    total: c.total,
    available: c.available,
    occupied: c.occupied,
    reserved: c.reserved,
    occupancyRate: +((c.occupied + c.reserved) / c.total).toFixed(3),
    revenueSession: +store.revenue.toFixed(2),
    hourlyRate: RATE,
    byLevel: [0, 1, 2, 3].map((lv) => ({ level: `P${lv}`, ...store.counts(lv) })),
    flow: store.flow,
    generatedAt: new Date().toISOString(),
  };
}

function respond(id) {
  switch (id) {
    case 'spots': {
      const all = store.spots.map(view);
      return [200, { count: all.length, data: all.slice(0, 6), truncated: `${all.length - 6} autres places…` }];
    }
    case 'available': {
      const all = store.spots.filter((s) => s.status === 'available').map(view);
      return [200, { count: all.length, data: all.slice(0, 6), truncated: `${Math.max(0, all.length - 6)} autres places…` }];
    }
    case 'reserve': {
      const best = store.suggestions(1)[0]?.spot;
      if (!best) return [409, { error: 'parking_full', message: 'Aucune place disponible' }];
      return [201, { reservationId: String(Math.floor(100000 + Math.random() * 900000)), spotId: best.id, plate: randomPlate(), durationH: 2, total: 2 * RATE, status: 'confirmed', dryRun: true }];
    }
    case 'cancel':
      return store.active ? [200, { reservationId: store.active.id, spotId: store.active.spotId, status: 'cancelled', dryRun: true }] : [404, { error: 'not_found', message: 'Aucune réservation active' }];
    case 'stats':
      return [200, stats()];
    case 'anpr':
      return [200, { plate: randomPlate(), cameraId: 'CAM-ENTREE-01', confidence: +(0.95 + Math.random() * 0.049).toFixed(3), authorized: true, readTimeMs: Math.round(320 + Math.random() * 120) }];
    default:
      return [404, { error: 'not_found' }];
  }
}

export class ApiPanel {
  constructor() {
    this.calls = 0;
    $('#endpoints').innerHTML = ENDPOINTS.map((e) => `<button class="endpoint" type="button" data-ep="${e.id}"><span class="method" style="--c:${COLORS[e.method]}">${e.method}</span><code>${e.url}</code><em>Tester</em><small>${e.desc}</small></button>`).join('');
    $('#endpoints').addEventListener('click', (e) => {
      const b = e.target.closest('.endpoint');
      if (b) this.test(b);
    });
    $('#api-tabs').addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      $$('#api-tabs button').forEach((x) => x.classList.toggle('is-active', x === b));
      $$('.tabpane').forEach((p) => p.classList.toggle('is-active', p.dataset.pane === b.dataset.tab));
    });
    $('#log-clear').addEventListener('click', () => ($('#api-log').innerHTML = '<p class="log__empty">Aucune requête — testez un endpoint</p>'));
    $('#webhook-test').addEventListener('click', () => this.webhook());
    let shown = false;
    let key = this._key();
    $('#key-reveal').addEventListener('click', (e) => {
      shown = !shown;
      $('#api-key').textContent = shown ? key : 'ap_live_••••••••••••••••••••••';
      e.currentTarget.textContent = shown ? 'Masquer' : 'Révéler';
    });
    $('#key-regen').addEventListener('click', () => {
      key = this._key();
      if (shown) $('#api-key').textContent = key;
      notify('Nouvelle clé générée (démonstration)');
    });
    $('#key-copy').addEventListener('click', () => {
      navigator.clipboard?.writeText($('#api-key-read').textContent).then(
        () => notify('Clé copiée'),
        () => notify('Copie impossible dans ce navigateur', true),
      );
    });
    $$('.exports button').forEach((b) => b.addEventListener('click', () => this.export(b.dataset.export)));
    const label = $('#storage-label');
    label.textContent = store.persisted ? 'LocalStorage actif' : 'LocalStorage indisponible';
  }

  _key() {
    const hex = [...crypto.getRandomValues(new Uint8Array(11))].map((b) => b.toString(16).padStart(2, '0')).join('');
    return `ap_live_${hex}`;
  }

  log(method, url, status) {
    const log = $('#api-log');
    log.querySelector('.log__empty')?.remove();
    const d = new Date();
    const row = document.createElement('div');
    row.innerHTML = `<time>${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}</time><span style="color:${COLORS[method] || 'inherit'}">${method}</span><span>${url}</span><span class="${status < 400 ? 'ok' : 'err'}">${status}</span>`;
    log.prepend(row);
    this.calls++;
    $('#api-usage').textContent = `${this.calls} requête${this.calls > 1 ? 's' : ''}`;
  }

  test(button) {
    const ep = ENDPOINTS.find((e) => e.id === button.dataset.ep);
    $$('.endpoint').forEach((b) => b.classList.toggle('is-active', b === button));
    const out = $('#api-response');
    out.textContent = `${ep.method} ${ep.url}\n…`;
    setTimeout(() => {
      const [status, body] = respond(ep.id);
      out.textContent = `${ep.method} https://api.autopark.local/v1${ep.url}\nHTTP ${status} · ${Math.round(40 + Math.random() * 90)} ms (simulé)\n\n${JSON.stringify(body, null, 2)}`;
      this.log(ep.method, ep.url, status);
    }, 260);
  }

  webhook() {
    const events = $$('#webhook-events input:checked').map((i) => i.value);
    const out = $('#webhook-result');
    out.hidden = false;
    if (!events.length) {
      out.textContent = '// Cochez au moins un événement';
      return;
    }
    const event = events[Math.floor(Math.random() * events.length)];
    const payload = { event, timestamp: new Date().toISOString(), data: { spotId: store.suggestions(1)[0]?.spot.id || 'P0-001', plate: randomPlate() } };
    out.textContent = `// Simulation : rien n'est envoyé à ${$('#webhook-url').value}\nPOST ${event}\n${JSON.stringify(payload, null, 2)}`;
    this.log('POST', `webhook → ${event}`, 200);
  }

  export(kind) {
    if (kind === 'spots') download('spots.json', JSON.stringify(store.spots.map(view), null, 2));
    else if (kind === 'history') download('reservations.json', JSON.stringify(store.history, null, 2));
    else if (kind === 'stats') download('stats.json', JSON.stringify(stats(), null, 2));
    else {
      const rows = [['recu', 'place', 'plaque', 'debut', 'fin', 'heures', 'total', 'statut']].concat(store.history.map((r) => [r.id, r.spotId, r.plate, new Date(r.start).toISOString(), new Date(r.end).toISOString(), r.hours, (r.total + (r.extra || 0)).toFixed(2), r.status]));
      download('reservations.csv', rows.map((r) => r.join(';')).join('\n'), 'text/csv');
    }
    notify('Fichier exporté');
  }
}
