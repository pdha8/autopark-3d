import { EASE_SCROLL } from '../core/util.js';

// Défilement plein écran, une section à la fois (molette, tactile, clavier, liens).

const SCROLLABLE = '.modal, .results, .endpoints, .log, .response, .history, input, textarea';

export class Sections {
  constructor({ container, count, duration = 1.05, onStart, onComplete, locked }) {
    this.container = container;
    this.count = count;
    this.duration = duration;
    this.onStart = onStart;
    this.onComplete = onComplete;
    this.locked = locked || (() => false);
    this.index = 0;
    this.y = 0; // défilement courant en px
    this.anim = null;
    this.enabled = false;
    this.height = window.innerHeight;
    this._lastWheel = 0;
    this._wheelAcc = 0;
    this._gestureUsed = false;

    window.addEventListener('wheel', (e) => this._onWheel(e), { passive: false });
    window.addEventListener('keydown', (e) => this._onKey(e));
    window.addEventListener('touchstart', (e) => this._onTouchStart(e), { passive: true });
    window.addEventListener('touchend', (e) => this._onTouchEnd(e), { passive: true });
  }

  get animating() {
    return !!this.anim;
  }

  resize(height) {
    this.height = height;
    if (!this.anim) {
      this.y = this.index * height;
      this._apply();
    }
  }

  goTo(i, instant = false) {
    i = Math.max(0, Math.min(this.count - 1, i));
    if (!this.enabled || this.anim || i === this.index) return false;
    const prev = this.index;
    this.index = i;
    this.onStart?.(i, prev);
    if (instant) {
      this.y = i * this.height;
      this._apply();
      this.onComplete?.(i, prev);
      return true;
    }
    this.anim = { from: this.y, to: i * this.height, t: 0, prev, next: i };
    return true;
  }

  next() {
    return this.goTo(this.index + 1);
  }

  prev() {
    return this.goTo(this.index - 1);
  }

  update(dt) {
    if (!this.anim) return;
    const a = this.anim;
    // les sauts de plusieurs sections durent un peu plus longtemps
    const dur = this.duration * (1 + 0.18 * (Math.abs(a.next - a.prev) - 1));
    a.t = Math.min(1, a.t + dt / dur);
    this.y = a.from + (a.to - a.from) * EASE_SCROLL(a.t);
    this._apply();
    if (a.t >= 1) {
      this.anim = null;
      this.y = a.to;
      this._apply();
      this.onComplete?.(a.next, a.prev);
    }
  }

  _apply() {
    this.container.style.transform = `translate3d(0, ${-this.y.toFixed(2)}px, 0)`;
  }

  _blocked(e) {
    if (this.locked()) return true;
    const el = e.target instanceof Element ? e.target.closest(SCROLLABLE) : null;
    return !!el && el.scrollHeight > el.clientHeight + 2;
  }

  _onWheel(e) {
    if (e.ctrlKey) return; // laisse le zoom du navigateur fonctionner
    if (this._blocked(e)) return;
    e.preventDefault();
    const now = performance.now();
    // un nouveau geste commence après une courte pause (évite l'inertie des pavés tactiles)
    if (now - this._lastWheel > 220) {
      this._wheelAcc = 0;
      this._gestureUsed = false;
    }
    this._lastWheel = now;
    if (this._gestureUsed || this.anim) return;
    this._wheelAcc += e.deltaMode === 1 ? e.deltaY * 30 : e.deltaY;
    if (Math.abs(this._wheelAcc) > 35) {
      const ok = this._wheelAcc > 0 ? this.next() : this.prev();
      if (ok) this._gestureUsed = true;
      this._wheelAcc = 0;
    }
  }

  _onKey(e) {
    if (this.locked()) return;
    if (e.target && /input|textarea|select/i.test(e.target.tagName)) return;
    // Espace sur un bouton ou un lien : on laisse le bouton s'activer, sans changer de section
    if ((e.key === ' ' || e.key === 'Spacebar') && e.target instanceof Element && e.target.closest('button, a, [role="link"]')) return;
    if (['ArrowDown', 'PageDown', ' ', 'Spacebar'].includes(e.key)) {
      e.preventDefault();
      this.next();
    } else if (['ArrowUp', 'PageUp'].includes(e.key)) {
      e.preventDefault();
      this.prev();
    } else if (e.key === 'Home') {
      this.goTo(0);
    } else if (e.key === 'End') {
      this.goTo(this.count - 1);
    }
  }

  _onTouchStart(e) {
    this._touchY = this._blocked(e) ? null : (e.touches[0]?.clientY ?? null);
  }

  _onTouchEnd(e) {
    if (this._touchY == null) return;
    const y = e.changedTouches[0]?.clientY ?? this._touchY;
    const dy = this._touchY - y;
    this._touchY = null;
    if (Math.abs(dy) > 45) (dy > 0 ? this.next() : this.prev());
  }
}
