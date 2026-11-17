// Calque 3D d'une section : vidéos rendues dans Blender (une par éclairage : nuit, jour),
// lues en boucle. Changer de thème bascule sur l'autre vidéo, calée sur la même image.

const HAS_RVFC = typeof HTMLVideoElement !== 'undefined' && 'requestVideoFrameCallback' in HTMLVideoElement.prototype;
export const VARIANTS = ['night', 'day'];

// Téléphone debout : seule une bande verticale de la vidéo est visible (autour du sujet, voir
// MOBILE_FOCUS dans main.js). Les vidéos *_m.mp4 ne contiennent que cette bande, marge comprise,
// à pleine résolution : [début, largeur] en fraction de la largeur de la vidéo complète.
const PHONE_CROP = { hero: [0.28485, 0.56667], gate: [0.53182, 0.35636], roof: [0.41727, 0.38182] };

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
    this.kind = 'full'; // 'full' ou 'phone' (vidéo recadrée)
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
    const m = this.kind === 'phone' && PHONE_CROP[this.name] ? '_m' : '';
    return `${import.meta.env.BASE_URL}video/${this.name}_${variant}${m}.${ext}`;
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
      this._place(el);
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

  /** Vidéo recadrée : elle n'occupe que sa bande dans le cadre de la scène. */
  _place(el) {
    const c = this.kind === 'phone' ? PHONE_CROP[this.name] : null;
    el.style.left = c ? `${(c[0] * 100).toFixed(3)}%` : '';
    el.style.width = c ? `${(c[1] * 100).toFixed(3)}%` : '';
  }

  /** Change de jeu de vidéos (téléphone debout ou non) en gardant l'instant de lecture. */
  setKind(kind) {
    if (kind === this.kind) return;
    this.kind = kind;
    this.frameTime = null;
    for (const [variant, el] of this.videos) {
      const t = el.currentTime;
      const play = !el.paused;
      el.addEventListener(
        'loadedmetadata',
        () => {
          el.currentTime = t;
          if (play) el.play().catch(() => {});
        },
        { once: true },
      );
      this._place(el);
      el.poster = this.url(variant, 'jpg');
      el.src = this.url(variant);
    }
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

  async setVariant(variant, preload = 'auto') {
    if (variant === this.variant) return;
    const id = ++this._switch;
    const cur = this.active;
    const next = this.get(variant, preload);
    if (!cur) {
      this.variant = variant;
      next.classList.add('is-active');
      return;
    }
    if (!(await this.ready(variant))) return; // vidéo manquante : on garde l'actuelle
    if (id !== this._switch) return; // un autre changement a eu lieu entre-temps
    const d = next.duration || cur.duration || 48;
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

}
