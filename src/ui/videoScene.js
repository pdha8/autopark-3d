// Calque 3D d'une section : vidéos rendues dans Blender (une par éclairage : nuit, jour),
// lues en boucle. Changer de thème bascule sur l'autre vidéo, calée sur la même image.

const HAS_RVFC = typeof HTMLVideoElement !== 'undefined' && 'requestVideoFrameCallback' in HTMLVideoElement.prototype;
export const VARIANTS = ['night', 'day'];

function once(el, type) {
  return new Promise((resolve) => el.addEventListener(type, resolve, { once: true }));
}

export class VideoScene {
  constructor(container, name) {
    this.container = container;
    this.root = container.querySelector('.scene__videos');
    this.name = name;
    this.videos = new Map();
    this.variant = null;
    this.playing = false;
    this.frameTime = null; // instant de l'image réellement affichée (requestVideoFrameCallback)
    this._switch = 0;
    // le navigateur met en pause les vidéos des onglets masqués : reprise au retour
    document.addEventListener('visibilitychange', () => {
      const el = this.active;
      if (!document.hidden && this.playing && el?.paused) el.play().catch(() => {});
    });
  }

  url(variant, ext = 'mp4') {
    return `${import.meta.env.BASE_URL}video/${this.name}_${variant}.${ext}`;
  }

  /** Crée (ou renvoie) l'élément vidéo d'une variante. */
  get(variant, preload = 'auto') {
    let el = this.videos.get(variant);
    if (!el) {
      el = document.createElement('video');
      el.muted = true;
      el.defaultMuted = true;
      el.loop = true;
      el.playsInline = true;
      el.disablePictureInPicture = true;
      el.setAttribute('muted', '');
      el.setAttribute('playsinline', '');
      el.setAttribute('aria-hidden', 'true');
      el.dataset.variant = variant;
      el.preload = preload;
      el.poster = this.url(variant, 'jpg'); // image fixe si la lecture automatique est bloquée
      el.src = this.url(variant);
      this.root.appendChild(el);
      this.videos.set(variant, el);
      if (HAS_RVFC) {
        const onFrame = (now, meta) => {
          if (el === this.active && !el.seeking) this.frameTime = meta.mediaTime;
          el.requestVideoFrameCallback(onFrame);
        };
        el.requestVideoFrameCallback(onFrame);
      }
    } else if (preload === 'auto' && el.preload !== 'auto') {
      el.preload = 'auto';
    }
    return el;
  }

  get active() {
    return this.variant ? this.videos.get(this.variant) : null;
  }

  /** Temps de la vidéo active (image affichée si le navigateur sait le dire). */
  get time() {
    const a = this.active;
    if (!a) return 0;
    const ft = this.frameTime;
    // image affichée si elle correspond à la position de lecture (sinon : valeur périmée après un saut)
    return ft !== null && Math.abs(ft - a.currentTime) < 0.25 ? ft : a.currentTime;
  }

  /** Résolu quand la vidéo peut être lue sans attendre (null si elle est introuvable). */
  ready(variant = this.variant, onProgress = null) {
    const el = this.get(variant);
    if (el.error) return Promise.resolve(null);
    if (el.readyState >= 3) return Promise.resolve(el);
    if (onProgress) {
      const tick = () => {
        if (el.duration && el.buffered.length) onProgress(Math.min(1, el.buffered.end(el.buffered.length - 1) / el.duration));
      };
      el.addEventListener('progress', tick);
      el.addEventListener('loadedmetadata', tick);
    }
    return Promise.race([
      once(el, 'canplaythrough').then(() => el),
      once(el, 'canplay').then(() => new Promise((r) => setTimeout(() => r(el), 400))),
      once(el, 'error').then(() => null),
    ]);
  }

  async setVariant(variant) {
    if (variant === this.variant) return;
    const id = ++this._switch;
    const cur = this.active;
    const next = this.get(variant);
    if (!cur) {
      this.variant = variant;
      next.classList.add('is-active');
      return;
    }
    if (!(await this.ready(variant))) return; // vidéo manquante : on garde l'actuelle
    if (id !== this._switch) return; // un autre changement a eu lieu entre-temps
    const d = next.duration || cur.duration || 12;
    next.currentTime = (this.time + 1 / 30) % d;
    await once(next, 'seeked');
    if (id !== this._switch) return;
    if (this.playing) await next.play().catch(() => {});
    this.variant = variant;
    this.frameTime = null;
    next.classList.add('is-active');
    cur.classList.remove('is-active');
    cur.pause();
  }

  play(fromStart = false) {
    const el = this.active;
    if (!el) return;
    this.playing = true;
    if (fromStart) {
      el.currentTime = 0;
      this.frameTime = null;
    }
    const p = el.play();
    if (p) p.catch(() => {});
  }

  pause() {
    this.playing = false;
    this.active?.pause();
  }

  /** Précharge l'autre éclairage (bascule jour / nuit instantanée). */
  preloadOthers() {
    for (const v of VARIANTS) if (v !== this.variant) this.get(v, 'auto');
  }
}
