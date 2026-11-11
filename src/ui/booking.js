// Réservation d'une place : choix de la durée, paiement simulé, reçu, compte à
// rebours, sortie, historique. Démonstration : rien n'est envoyé.

import { store, RATE, randomPlate } from '../core/store.js';
import { $, $$, clock, duration, euro, hhmm } from '../core/util.js';

let notifTimer = 0;
export function notify(message, error = false) {
  const el = $('#notif');
  el.textContent = message;
  el.classList.toggle('is-error', error);
  el.classList.add('is-on');
  clearTimeout(notifTimer);
  notifTimer = setTimeout(() => el.classList.remove('is-on'), 2600);
}

const alertQueue = [];
const alertSeen = {};
let alertBusy = false;
export function alertBanner(message, kind = 'warn', key = message) {
  const now = Date.now();
  if (alertSeen[key] && now - alertSeen[key] < 45000) return;
  alertSeen[key] = now;
  alertQueue.push({ message, kind });
  if (!alertBusy) nextAlert();
}

function nextAlert() {
  const item = alertQueue.shift();
  const el = $('#alert');
  if (!item) {
    alertBusy = false;
    return;
  }
  alertBusy = true;
  el.textContent = item.message;
  el.classList.toggle('is-danger', item.kind === 'danger');
  el.classList.add('is-on');
  setTimeout(() => {
    el.classList.remove('is-on');
    setTimeout(nextAlert, 500);
  }, 3800);
}

export function openModal(id) {
  const m = $(`#${id}`);
  m.hidden = false;
  m.querySelector('input, button:not(.modal__close)')?.focus({ preventScroll: true });
}

export function closeModal(id) {
  $(`#${id}`).hidden = true;
}

export const modalOpen = () => $$('.modal').some((m) => !m.hidden);

export class Booking {
  constructor({ onGuide }) {
    this.onGuide = onGuide;
    this.spot = null;
    this.hours = 2;

    for (const m of $$('.modal')) {
      m.addEventListener('click', (e) => {
        if (e.target === m || e.target.closest('[data-close]')) m.hidden = true;
      });
    }
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') $$('.modal').forEach((m) => (m.hidden = true));
    });

    $('#durations').addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      this.hours = +b.dataset.h;
      $$('#durations button').forEach((x) => x.classList.toggle('is-active', x === b));
      this._price();
    });
    $('#res-plate').addEventListener('keydown', (e) => e.key === 'Enter' && this.confirm());
    $('#res-confirm').addEventListener('click', () => this.confirm());
    $('#rec-navigate').addEventListener('click', () => {
      closeModal('modal-receipt');
      if (store.active) this.onGuide(store.active.spotId);
    });
    $('#ar-guide').addEventListener('click', () => store.active && this.onGuide(store.active.spotId));
    $('#ar-end').addEventListener('click', () => this.askExit());
    $('#ex-pay').addEventListener('click', () => this.pay());
    $('#btn-history').addEventListener('click', () => {
      this.renderHistory();
      openModal('modal-history');
    });
    store.addEventListener('reservation', () => this.renderBar());
    this.renderBar();
    this._arrival = 0;
  }

  /** Ouvre la fenêtre de réservation pour une place (ou la meilleure place libre). */
  open(spot = null) {
    if (store.active) {
      notify('Vous avez déjà une réservation en cours', true);
      return;
    }
    spot ||= store.suggestions(1)[0]?.spot;
    if (!spot || spot.status !== 'available') {
      notify('Aucune place disponible', true);
      return;
    }
    this.spot = spot;
    $('#res-spot').textContent = `${spot.id} · niveau P${spot.level}`;
    $('#res-plate').value = '';
    this._price();
    openModal('modal-reserve');
  }

  _price() {
    $('#res-duration').textContent = `${this.hours} h`;
    $('#res-total').textContent = euro(this.hours * RATE);
  }

  confirm() {
    const input = $('#res-plate');
    const plate = (input.value.trim().toUpperCase() || randomPlate()).slice(0, 12);
    const res = store.reserve(this.spot.id, plate, this.hours);
    if (!res) {
      notify('Cette place vient d’être prise', true);
      closeModal('modal-reserve');
      return;
    }
    closeModal('modal-reserve');
    $('#rec-id').textContent = res.id;
    $('#rec-spot').textContent = res.spotId;
    $('#rec-plate').textContent = res.plate;
    $('#rec-start').textContent = hhmm(res.start);
    $('#rec-end').textContent = hhmm(res.end);
    $('#rec-dur').textContent = `${res.hours} h`;
    $('#rec-total').textContent = euro(res.total);
    openModal('modal-receipt');
    // quelques secondes plus tard, la voiture arrive sur sa place
    clearTimeout(this._arrival);
    this._arrival = setTimeout(() => {
      const spot = store.byId.get(res.spotId);
      if (store.active?.id === res.id && spot?.status === 'reserved') {
        store.set(spot, 'occupied', res.plate, 'arrival');
        notify(`Véhicule ${res.plate} garé en ${spot.id}`);
      }
    }, 7000);
  }

  askExit() {
    const bill = store.exitBill();
    if (!bill) return;
    $('#ex-spot').textContent = bill.res.spotId;
    $('#ex-plate').textContent = bill.res.plate;
    $('#ex-dur').textContent = duration(bill.real);
    $('#ex-over').textContent = bill.over > 0 ? `${duration(bill.over)} (+50 %)` : 'Aucun';
    $('#ex-total').textContent = euro(bill.due);
    openModal('modal-exit');
  }

  pay() {
    const bill = store.endActive();
    closeModal('modal-exit');
    if (bill) notify(`Place ${bill.res.spotId} libérée · merci de votre visite`);
  }

  renderBar() {
    const bar = $('#resbar');
    const r = store.active;
    bar.hidden = !r;
    if (!r) return;
    $('#ar-id').textContent = r.spotId;
    $('#ar-plate').textContent = r.plate;
    this.tick();
  }

  /** Compte à rebours (appelé une fois par seconde). */
  tick() {
    const r = store.active;
    if (!r) return;
    const left = r.end - Date.now();
    const el = $('#ar-timer');
    el.textContent = clock(left);
    el.classList.toggle('is-late', left < 0);
    if (left > 0 && left < 10 * 60000) alertBanner(`Votre réservation expire dans ${Math.ceil(left / 60000)} min`, 'warn', 'expiry');
    else if (left < 0) alertBanner('Dépassement de durée — majoration de 50 % en cours', 'danger', 'overstay');
  }

  renderHistory() {
    const list = $('#history-list');
    if (!store.history.length) {
      list.innerHTML = '<p class="history__empty">Aucune réservation pour le moment</p>';
      return;
    }
    const now = Date.now();
    list.innerHTML = store.history
      .map((r) => {
        const active = r.status === 'active';
        const late = active && now > r.end;
        const right = active ? `<strong class="${late ? 'is-late' : ''}">${clock(r.end - now)}</strong><small>${late ? 'Dépassement' : 'En cours'}</small>` : `<strong>${euro(r.total + (r.extra || 0))}</strong><small>Terminée</small>`;
        return `<div class="history__item"><div><b>${r.spotId}</b><i>${r.plate}</i><small>Reçu #${r.id} · ${hhmm(r.start)} → ${hhmm(r.end)} · ${r.hours} h</small></div><div>${right}</div></div>`;
      })
      .join('');
  }
}
