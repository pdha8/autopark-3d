// État du parking : 240 places, simulation « live », réservations, historique.
// Tout reste dans le navigateur (LocalStorage) : rien n'est envoyé.

import layout from '../data/layout.json';
import sync from '../data/sync.json';

const KEY = 'autopark3d.etat.v1';
const LETTERS = 'ABCDEFGHJKLMNPQRSTVWXYZ';
const STATUSES = ['available', 'occupied', 'reserved'];
export const RATE = layout.rate; // € / heure
export const OVERSTAY = 1.5; // majoration en cas de dépassement
// places pilotées par la vidéo (la voiture bleue s'y gare en boucle) : hors simulation
export const LOCKED = new Set([sync.bay, sync.passBay]);
const ROW_Y = [2.5, 13.5, 18.5, 29.5];

export function randomPlate() {
  const l = () => LETTERS[Math.floor(Math.random() * LETTERS.length)];
  const d = () => Math.floor(Math.random() * 10);
  return `${l()}${l()}-${d()}${d()}${d()}-${l()}${l()}`;
}

class Store extends EventTarget {
  constructor() {
    super();
    this.live = true;
    this.persisted = false;
    this._clock = 0;
    this._next = 2.5 + Math.random() * 3;
    this.reset(false);
    this._load();
  }

  reset(notify = true) {
    this.spots = layout.spots.map((s) => ({ ...s, plate: s.status === 'occupied' ? s.plate : null, mine: false }));
    this.byId = new Map(this.spots.map((s) => [s.id, s]));
    this.history = [];
    this.active = null;
    this.feed = [];
    this.revenue = 0;
    this.flow = { in: 0, out: 0 };
    if (notify) {
      this._save();
      this._emit('change', {});
      this._emit('reservation', {});
    }
  }

  // ------------------------------------------------------------ lecture
  counts(level = null) {
    const out = { available: 0, occupied: 0, reserved: 0, total: 0 };
    for (const s of this.spots) {
      if (level !== null && s.level !== level) continue;
      out[s.status]++;
      out.total++;
    }
    return out;
  }

  byType() {
    const out = {};
    for (const s of this.spots) {
      const t = (out[s.type] ||= { total: 0, used: 0 });
      t.total++;
      if (s.status !== 'available') t.used++;
    }
    return out;
  }

  /** Note d'une place libre (0 à 1) : proche de la rampe, niveau bas, rangée peu chargée. */
  score(s) {
    if (s.status !== 'available' || LOCKED.has(s.id)) return -1;
    const x = (s.col + 0.5) * 2.7;
    const drive = Math.hypot(46.5 - x, ROW_Y[s.row] - 8) + (layout.levels - 1 - s.level) * 0 + s.level * 38;
    const mates = this.spots.filter((o) => o.level === s.level && o.row === s.row && o.status !== 'available').length;
    const bonus = s.type === 'pmr' ? 0.1 : s.type === 'std' ? 0 : 0.05;
    return Math.min(1, (1 - Math.min(1, drive / 170)) * 0.5 + (1 - s.level * 0.15) * 0.25 + (1 - mates / layout.cols) * 0.2 + bonus);
  }

  walk(s) {
    return Math.round(Math.hypot((s.col + 0.5) * 2.7 + 6, ROW_Y[s.row] - 2));
  }

  suggestions(n = 4, level = null) {
    return this.spots
      .filter((s) => s.status === 'available' && s.type === 'std' && (level === null || s.level === level))
      .map((s) => ({ spot: s, score: this.score(s) }))
      .filter((o) => o.score >= 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, n);
  }

  search(q) {
    q = q.trim().toUpperCase();
    if (!q) return [];
    return this.spots.filter((s) => s.id.includes(q) || (s.plate && s.plate.replace(/-/g, '').includes(q.replace(/-/g, '')))).slice(0, 6);
  }

  // ------------------------------------------------------------ écriture
  set(spot, status, plate = null, type = null) {
    const prev = spot.status;
    spot.status = status;
    spot.plate = status === 'available' ? null : plate || spot.plate;
    if (status === 'available') spot.mine = false;
    if (type) {
      this.feed.unshift({ time: Date.now(), type, id: spot.id, plate: spot.plate });
      this.feed.length = Math.min(this.feed.length, 40);
      if (type === 'arrival') this.flow.in++;
      if (type === 'departure') this.flow.out++;
    }
    this._save();
    this._emit('change', { spot, prev, type });
  }

  arrive(spot = null, plate = null) {
    const pool = this.spots.filter((s) => s.status === 'available' && !LOCKED.has(s.id));
    spot ||= pool[Math.floor(Math.random() * pool.length)];
    if (!spot) return null;
    this.set(spot, 'occupied', plate || randomPlate(), 'arrival');
    return spot;
  }

  depart(spot = null) {
    const pool = this.spots.filter((s) => s.status === 'occupied' && !s.mine && !LOCKED.has(s.id));
    spot ||= pool[Math.floor(Math.random() * pool.length)];
    if (!spot) return null;
    this.set(spot, 'available', null, 'departure');
    return spot;
  }

  /** Avance la simulation « live » (arrivées, départs, réservations d'autres usagers). */
  tick(dt) {
    if (!this.live) return;
    this._clock += dt;
    if (this._clock < this._next) return;
    this._clock = 0;
    this._next = 3.5 + Math.random() * 5.5;
    const c = this.counts();
    const rate = (c.occupied + c.reserved) / c.total;
    const arrivalBias = rate > 0.8 ? 0.25 : rate < 0.3 ? 0.8 : 0.55;
    if (Math.random() < arrivalBias) {
      const booked = this.spots.filter((s) => s.status === 'reserved' && !s.mine && !LOCKED.has(s.id));
      if (booked.length > 30 || (booked.length && Math.random() < 0.5)) {
        this.set(booked[Math.floor(Math.random() * booked.length)], 'occupied', randomPlate(), 'arrival');
      } else if (c.reserved < 36 || Math.random() < 0.35) {
        const free = this.spots.filter((s) => s.status === 'available' && !LOCKED.has(s.id));
        if (free.length) this.set(free[Math.floor(Math.random() * free.length)], 'reserved', null, 'booking');
      } else {
        this.arrive();
      }
    } else {
      this.depart();
    }
  }

  reserve(spotId, plate, hours) {
    const spot = this.byId.get(spotId);
    if (!spot || spot.status !== 'available' || this.active) return null;
    const now = Date.now();
    const res = { id: String(Math.floor(100000 + Math.random() * 900000)), spotId, plate, start: now, end: now + hours * 3600e3, hours, total: hours * RATE, status: 'active', extra: 0 };
    spot.mine = true;
    this.active = res;
    this.history.unshift(res);
    this.revenue += res.total;
    this.set(spot, 'reserved', plate, 'booking');
    this._emit('reservation', { res });
    return res;
  }

  /** Montant dû à la sortie : la durée réservée est déjà payée, seul le dépassement est majoré. */
  exitBill() {
    const r = this.active;
    if (!r) return null;
    const now = Date.now();
    const over = Math.max(0, now - r.end);
    return { res: r, real: now - r.start, over, due: (over / 3600e3) * RATE * OVERSTAY };
  }

  endActive() {
    const bill = this.exitBill();
    if (!bill) return null;
    const { res } = bill;
    res.status = 'done';
    res.finished = Date.now();
    res.extra = bill.due;
    this.revenue += bill.due;
    this.active = null;
    const spot = this.byId.get(res.spotId);
    if (spot) this.set(spot, 'available', null, 'departure');
    this._emit('reservation', { res });
    return bill;
  }

  // ------------------------------------------------------------ persistance
  _save() {
    try {
      const data = {
        s: this.spots.map((s) => [STATUSES.indexOf(s.status), s.plate, s.mine ? 1 : 0]),
        h: this.history.slice(0, 30),
        a: this.active ? this.active.id : null,
        r: this.revenue,
        f: this.flow,
      };
      localStorage.setItem(KEY, JSON.stringify(data));
      this.persisted = true;
    } catch {
      this.persisted = false;
    }
  }

  _load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) {
        localStorage.setItem(`${KEY}.test`, '1');
        localStorage.removeItem(`${KEY}.test`);
        this.persisted = true;
        return;
      }
      const data = JSON.parse(raw);
      if (!Array.isArray(data.s) || data.s.length !== this.spots.length) return;
      data.s.forEach(([st, plate, mine], i) => {
        const s = this.spots[i];
        if (LOCKED.has(s.id)) return;
        s.status = STATUSES[st] || s.status;
        s.plate = plate;
        s.mine = !!mine;
      });
      this.history = data.h || [];
      this.active = this.history.find((r) => r.id === data.a && r.status === 'active') || null;
      this.revenue = data.r || 0;
      this.flow = data.f || this.flow;
      this.persisted = true;
    } catch {
      this.persisted = false;
    }
  }

  _emit(name, detail) {
    this.dispatchEvent(new CustomEvent(name, { detail }));
  }
}

export const store = new Store();
