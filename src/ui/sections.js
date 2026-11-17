import { EASE_SCROLL } from '../core/util.js';

// Défilement plein écran, une section à la fois (molette, tactile, clavier, liens).


export class Sections {
  constructor({ container, count, duration = 1.05, onStart, onComplete, locked, instant }) {
    this.instant = instant || (() => false); // mouvement réduit : changement de section immédiat
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
    // contenu qui défile (mode compact, sections de contenu) : on arrive par le bon bout
    const sec = this.container.children[i];
    for (const el of [sec, sec?.querySelector('.ui--wide')]) {
      if (el && el.scrollHeight > el.clientHeight + 2) el.scrollTop = i > prev ? 0 : el.scrollHeight;
    }
    this.onStart?.(i, prev);
    if (instant || this.instant()) {
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

  /** Élément qui défile (barre interne) le plus proche de el, ou null. */
  _scroller(el) {
    for (let e = el instanceof Element ? el : null; e && e !== document.body; e = e.parentElement) {
      const oy = getComputedStyle(e).overflowY;
      if ((oy === 'auto' || oy === 'scroll') && e.scrollHeight > e.clientHeight + 2) return e;
    }
    return null;
  }

  /** Contenu qui défile dans la section affichée : élément au focus d'abord, puis la section. */
  _activeScroller() {
    const sec = this.container.children[this.index];
    if (!sec) return null;
    const a = document.activeElement;
    const own = a instanceof Element && sec.contains(a) ? this._scroller(a) : null;
    return own || this._scroller(sec.querySelector('.ui--wide')) || this._scroller(sec);
  }

  /** Peut-il encore défiler dans ce sens (dir > 0 : vers le bas) ? */
  static _canScroll(el, dir) {
    return dir > 0 ? el.scrollTop + el.clientHeight < el.scrollHeight - 2 : el.scrollTop > 2;
  }

  _onWheel(e) {
    if (e.ctrlKey) return; // laisse le zoom du navigateur fonctionner
    if (this.locked()) return;
    const now = performance.now();
    // un contenu qui défile passe d'abord ; la section change au geste suivant, une fois au bout
    const sc = this._scroller(e.target);
    if (sc && e.deltaY && Sections._canScroll(sc, Math.sign(e.deltaY))) {
      this._lastWheel = now;
      this._gestureUsed = true;
      return;
    }
    e.preventDefault();
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
    const down = ['ArrowDown', 'PageDown', ' ', 'Spacebar'].includes(e.key);
    if (down || ['ArrowUp', 'PageUp'].includes(e.key)) {
      e.preventDefault();
      // contenu plus haut que l'écran : on le fait défiler avant de changer de section
      const sc = this._activeScroller();
      if (sc && Sections._canScroll(sc, down ? 1 : -1)) {
        const step = e.key.startsWith('Arrow') ? 0.3 : 0.85;
        sc.scrollBy({ top: (down ? 1 : -1) * sc.clientHeight * step, behavior: 'smooth' });
        return;
      }
      if (down) this.next();
      else this.prev();
    } else if (e.key === 'Home') {
      this.goTo(0);
    } else if (e.key === 'End') {
      this.goTo(this.count - 1);
    }
  }

  _onTouchStart(e) {
    if (this.locked()) {
      this._touchY = null;
      return;
    }
    // au début du geste : le contenu touché pouvait-il encore défiler ?
    const sc = this._scroller(e.target);
    this._touchScroll = sc ? { up: Sections._canScroll(sc, -1), down: Sections._canScroll(sc, 1) } : null;
    this._touchY = e.touches[0]?.clientY ?? null;
  }

  _onTouchEnd(e) {
    if (this._touchY == null) return;
    const y = e.changedTouches[0]?.clientY ?? this._touchY;
    const dy = this._touchY - y;
    this._touchY = null;
    if (Math.abs(dy) <= 45) return;
    const sc = this._touchScroll;
    if (sc && (dy > 0 ? sc.down : sc.up)) return; // le geste a fait défiler le contenu
    if (dy > 0) this.next();
    else this.prev();
  }
}
