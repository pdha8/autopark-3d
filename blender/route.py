"""
Trajectoires des véhicules d'AutoPark 3D (mathématiques pures : numpy seul).

  - chemins : lignes, arcs, lignes brisées à angles arrondis, lissés (transitions de
    courbure progressives) ;
  - Run : un tronçon parcouru dans un seul sens (marche avant ou arrière), avec sa
    vitesse maximale en chaque point (zone, virage) ;
  - Trip : un trajet complet (suite de tronçons séparés par des arrêts) une fois
    cadencé par le simulateur de traffic.py ; il donne la pose du véhicule à tout
    instant : position, cap, braquage, rotation des roues (sans glissement),
    tangage sur les rampes, petits mouvements de caisse.

Tout est fonction du temps : la boucle vidéo se referme exactement.
"""

import math

import numpy as np

DS = 0.05  # pas d'échantillonnage des chemins (m)
SIGMA = 0.8  # lissage des chemins (m)
DT = 1.0 / 240.0  # pas de la table temporelle (s)
SIGMA_T = 0.16  # lissage des vitesses (s) : accélérations continues


# --------------------------------------------------------------------- géométrie
def line(p0, p1, z0, z1=None):
    z1 = z0 if z1 is None else z1
    n = max(2, int(math.dist(p0, p1) / DS) + 1)
    t = np.linspace(0.0, 1.0, n)
    return np.stack([p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t, z0 + (z1 - z0) * t], axis=1)


def arc(center, r, a0, a1, z0, z1=None):
    z1 = z0 if z1 is None else z1
    n = max(2, int(abs(math.radians(a1 - a0)) * r / DS) + 1)
    t = np.linspace(0.0, 1.0, n)
    a = np.radians(a0 + (a1 - a0) * t)
    return np.stack([center[0] + r * np.cos(a), center[1] + r * np.sin(a), z0 + (z1 - z0) * t], axis=1)


def fillet(pts, z):
    """Ligne brisée à angles arrondis. pts : (x, y) ou (x, y, rayon du virage en ce point)."""
    P = [(p[0], p[1]) for p in pts]
    R = [p[2] if len(p) > 2 else 0.0 for p in pts]
    out, cur = [], P[0]
    for i in range(1, len(P) - 1):
        a, b, c = P[i - 1], P[i], P[i + 1]
        u = np.array([b[0] - a[0], b[1] - a[1]])
        w = np.array([c[0] - b[0], c[1] - b[1]])
        lu, lw = np.linalg.norm(u), np.linalg.norm(w)
        u, w = u / lu, w / lw
        cross = u[0] * w[1] - u[1] * w[0]
        phi = math.atan2(cross, float(u @ w))  # angle du virage (positif : à gauche)
        if R[i] <= 0 or abs(phi) < 1e-4:
            out.append(line(cur, b, z))
            cur = b
            continue
        t = R[i] * math.tan(abs(phi) / 2)
        assert t < lu + 1e-6 and t < lw + 1e-6, f"virage trop large au point {i} {b} : {t:.2f} m pour {lu:.2f} / {lw:.2f} m"
        sgn = 1.0 if phi > 0 else -1.0
        pin = (b[0] - u[0] * t, b[1] - u[1] * t)
        cen = (pin[0] - u[1] * R[i] * sgn, pin[1] + u[0] * R[i] * sgn)
        a0 = math.degrees(math.atan2(pin[1] - cen[1], pin[0] - cen[0]))
        out.append(line(cur, pin, z))
        out.append(arc(cen, R[i], a0, a0 + math.degrees(phi), z))
        cur = (b[0] + w[0] * t, b[1] + w[1] * t)
    out.append(line(cur, P[-1], z))
    return out


def _smooth(a, sigma):
    r = max(1, int(4 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    r = min(r, len(a) - 1)
    k = k[len(k) // 2 - r : len(k) // 2 + r + 1]
    k /= k.sum()
    left = 2 * a[0] - a[r:0:-1]
    right = 2 * a[-1] - a[-2 : -r - 2 : -1]
    return np.convolve(np.concatenate([left, a, right]), k, mode="valid")


class Run:
    """Tronçon parcouru dans un seul sens. zfun(x, y) -> z remplace l'altitude des pièces."""

    def __init__(self, pieces, wb, reverse=False, zfun=None):
        pts = np.concatenate(pieces, axis=0)
        seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
        pts = pts[np.concatenate([[True], seg > 1e-9])]
        cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1])))])
        self.L = float(cum[-1])
        n = max(2, int(round(self.L / DS)))
        self.q = np.linspace(0.0, self.L, n + 1)
        self.ds = self.L / n
        s = SIGMA / self.ds
        self.x = _smooth(np.interp(self.q, cum, pts[:, 0]), s)
        self.y = _smooth(np.interp(self.q, cum, pts[:, 1]), s)
        self.z = np.interp(self.q, cum, pts[:, 2])
        if zfun is not None:
            self.z = _smooth(np.array([zfun(x, y, z) for x, y, z in zip(self.x, self.y, self.z)]), 0.5 / self.ds)
        self.reverse = reverse
        self.sign = -1.0 if reverse else 1.0
        travel = np.unwrap(np.arctan2(np.gradient(self.y, self.ds), np.gradient(self.x, self.ds)))
        self.heading = travel + (math.pi if reverse else 0.0)  # cap du véhicule
        k = np.gradient(travel, self.ds)
        self.kappa = -k if reverse else k  # courbure vue par le véhicule (marche avant)
        d = -wb if reverse else wb
        self.zf = np.interp(np.clip(self.q + d, 0.0, self.L), self.q, self.z)  # sol sous l'essieu avant
        self.cap = np.full(n + 1, 30.0)  # vitesse maximale (m/s)

    def limit(self, v, q0=None, q1=None):
        """Plafonne la vitesse entre q0 et q1 (tout le tronçon par défaut)."""
        m = (self.q >= (0.0 if q0 is None else q0) - 1e-9) & (self.q <= (self.L if q1 is None else q1) + 1e-9)
        self.cap[m] = np.minimum(self.cap[m], v)
        return self

    def q_at(self, axis, value, start=0.0):
        """Première abscisse (après start) où la coordonnée « x » ou « y » franchit value."""
        a = (self.x if axis == "x" else self.y) - value
        i0 = int(np.searchsorted(self.q, start))
        idx = np.nonzero(np.sign(a[i0:-1]) != np.sign(a[i0 + 1 :]))[0]
        assert len(idx), f"le tronçon ne franchit jamais {axis} = {value}"
        i = i0 + int(idx[0])
        return float(self.q[i] + self.ds * a[i] / (a[i] - a[i + 1]))

    def at(self, q):
        q = np.asarray(q, dtype=float)
        return {k: np.interp(q, self.q, getattr(self, k)) for k in ("x", "y", "z", "zf", "heading", "kappa")}

    def vmax(self, a_lat):
        return np.minimum(self.cap, np.sqrt(a_lat / np.maximum(np.abs(self.kappa), 1e-6)))

    def profile(self, a_lat, brake, q_stop=None):
        """Vitesse de consigne : plafonds, virages, freinage anticipé jusqu'à l'arrêt en q_stop."""
        v2 = self.vmax(a_lat) ** 2
        if q_stop is not None:
            i = min(len(v2) - 1, int(round(q_stop / self.ds)))
            v2 = v2.copy()
            v2[i:] = 0.0
        w = v2 + 2 * brake * self.q
        return np.sqrt(np.maximum(np.minimum.accumulate(w[::-1])[::-1] - 2 * brake * self.q, 0.0))


class Leg:
    """Un tronçon et ses arrêts. stops : [(abscisse, durée minimale, nom)] ;
    end = (durée, nom, garé) : arrêt en bout de tronçon (None : le trajet s'achève en roulant)."""

    def __init__(self, run, stops=(), end=None, name=""):
        self.run, self.stops, self.end, self.name = run, sorted(stops), end, name


# --------------------------------------------------------------------- trajet cadencé
class Trip:
    def __init__(self, legs, d, v0=0.0):
        self.legs, self.d, self.v0 = legs, d, v0
        self.marks = {}  # nom -> abscisse (tronçon, q) : instants calculés après la simulation
        self.T = 0.0

    def mark(self, name, leg, q):
        self.marks[name] = (leg, q)

    def set_motion(self, t, leg, q, events, parked):
        """t, leg, q : sortie du simulateur (pas constant). events : nom -> instant.
        parked : intervalles [(t0, t1)] où le véhicule est garé."""
        self.raw = (np.asarray(t), np.asarray(leg), np.asarray(q))
        self.T = float(t[-1])
        n = int(round(self.T / DT))
        self.t = np.linspace(0.0, self.T, n + 1)
        cols = {k: np.zeros(n + 1) for k in ("x", "y", "z", "zf", "psi", "kappa", "v", "a", "dist")}
        self.events, self.parked = dict(events), list(parked)
        psi_end, dist0 = None, 0.0
        dt = self.T / n
        for i, lg in enumerate(self.legs):
            run = lg.run
            sel = np.nonzero(leg == i)[0]
            ta, tb = t[sel[0]], t[sel[-1]]
            m = (self.t >= ta - 1e-9) & (self.t <= tb + 1e-9) if i == len(self.legs) - 1 else (self.t >= ta - 1e-9) & (self.t < tb - 1e-9)
            qq = np.interp(self.t[m], t[sel], q[sel])
            if m.sum() > 8:
                qq = np.clip(_smooth(qq, SIGMA_T / dt), 0.0, run.L)
            st = run.at(qq)
            head = st["heading"]
            if psi_end is not None:  # cap continu d'un tronçon au suivant
                head = head + 2 * math.pi * round((psi_end - head[0]) / (2 * math.pi))
            psi_end = head[-1]
            for key, arr in (("x", st["x"]), ("y", st["y"]), ("z", st["z"]), ("zf", st["zf"]), ("psi", head), ("kappa", st["kappa"])):
                cols[key][m] = arr
            v = np.gradient(qq, dt) if len(qq) > 1 else np.zeros_like(qq)
            cols["v"][m] = v * run.sign
            cols["dist"][m] = dist0 + (qq - qq[0]) * run.sign
            dist0 = cols["dist"][m][-1]
            for name, (li, qm) in self.marks.items():  # premier passage à l'abscisse marquée
                if li == i and name not in self.events:
                    k = int(np.argmax(qq >= qm - 1e-6)) if qq[-1] >= qm - 1e-6 else len(qq) - 1
                    self.events[name] = float(self.t[m][k])
        cols["a"] = np.gradient(cols["v"], dt)
        wb = self.d.wb
        cols["steer"] = np.arctan(wb * cols["kappa"])
        cols["pitch"] = np.arctan2(cols["zf"] - cols["z"], wb)
        # petits mouvements de caisse : cabrage à l'accélération, roulis en virage
        cols["dpitch"] = np.clip(0.0035 * cols["a"], -0.022, 0.022)
        cols["droll"] = np.clip(0.0022 * cols["v"] ** 2 * cols["kappa"], -0.028, 0.028)
        self.c = cols
        return self

    def sample(self, tau):
        """État du véhicule à l'instant tau du trajet (scalaire ou tableau) ;
        « on » vaut 0 hors de [0, T] : le véhicule est alors retiré de la scène."""
        tau = np.asarray(tau, dtype=float)
        out = {k: np.interp(tau, self.t, arr) for k, arr in self.c.items()}
        out["on"] = ((tau >= 0.0) & (tau <= self.T)).astype(float)
        return out

    def is_parked(self, tau):
        tau = np.asarray(tau, dtype=float)
        m = np.zeros(tau.shape, dtype=bool)
        for a, b in self.parked:
            m |= (tau >= a) & (tau <= b)
        return m

    def when(self, name):
        return self.events[name]


def corners(st, d, margin=0.0):
    """Coins au sol de la carrosserie (4 points x, y) pour un état sample() scalaire."""
    c, s = math.cos(float(st["psi"])), math.sin(float(st["psi"]))
    x, y = float(st["x"]), float(st["y"])
    return [(x + a * c - b * s, y + a * s + b * c) for a, b in ((d.nose + margin, d.half_w + margin), (d.nose + margin, -d.half_w - margin), (-d.tail - margin, -d.half_w - margin), (-d.tail - margin, d.half_w + margin))]
