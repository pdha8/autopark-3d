"""
Trajet des voitures « héros » d'AutoPark 3D (mathématiques pures : numpy seul).

Une seule route, parcourue par N_CARS voitures identiques décalées d'une boucle :
  route d'accès -> arrêt à la barrière (lecture de plaque) -> rampe hélicoïdale
  (voie extérieure, montée) -> toit -> place réservée -> marche arrière ->
  toit -> rampe (voie intérieure, descente) -> barrière de sortie -> route.

La pose de la voiture k à l'instant t de la boucle est route(t + k * LOOP) :
à la fin de la boucle, la voiture k est exactement là où était la voiture k+1
au début (même angle de roues, même braquage) -> raccord parfait.

Tout est fonction du temps : vitesses raccordées en « smootherstep » (accélération
continue), cap lissé (gaussien, réflexion impaire aux extrémités), roues qui
roulent sans glisser (angle = distance / rayon).
"""

import math

import numpy as np

import config as C

DS = 0.05  # pas d'échantillonnage du chemin (m)
SIGMA = 0.8  # lissage du chemin (m)
DT = 1.0 / 240.0  # pas de la table temporelle (s)

WB = 1.06 * C.CAR_SCALE  # empattement
NOSE = 1.396 * C.CAR_SCALE  # essieu arrière -> nez
TAIL = 0.340 * C.CAR_SCALE  # essieu arrière -> arrière
HALF_W = 0.455 * C.CAR_SCALE
AXLE_Y = 0.53 * C.CAR_SCALE  # origine du modèle -> essieu arrière
TRACK = 0.37 * C.CAR_SCALE

V_ROAD = 9.0
TOTAL = C.N_CARS * C.LOOP

STOP_GAP = 1.2  # distance nez -> lisse à l'arrêt
Y_STOP = C.GATE_IN_Y - STOP_GAP - NOSE  # y de l'essieu arrière à l'arrêt
DWELL = 4.0  # temps garé sur la place (s)
STAGGER = 66.0  # arrêt à l'entrée -> passage à la sortie : décalés d'une demi-boucle


# --------------------------------------------------------------------- géométrie
def _line(p0, p1, z0, z1=None):
    z1 = z0 if z1 is None else z1
    n = max(2, int(math.dist(p0, p1) / DS) + 1)
    t = np.linspace(0.0, 1.0, n)
    return np.stack([p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t, z0 + (z1 - z0) * t], axis=1)


def _arc(center, r, a0, a1, z0, z1=None):
    z1 = z0 if z1 is None else z1
    n = max(2, int(abs(math.radians(a1 - a0)) * r / DS) + 1)
    t = np.linspace(0.0, 1.0, n)
    a = np.radians(a0 + (a1 - a0) * t)
    return np.stack([center[0] + r * np.cos(a), center[1] + r * np.sin(a), z0 + (z1 - z0) * t], axis=1)


def _smooth(a, sigma):
    r = int(4 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    left = 2 * a[0] - a[r:0:-1]
    right = 2 * a[-1] - a[-2 : -r - 2 : -1]
    return np.convolve(np.concatenate([left, a, right]), k, mode="valid")


class Run:
    """Tronçon parcouru dans un seul sens (marche avant ou arrière)."""

    def __init__(self, pieces, reverse=False):
        pts = np.concatenate(pieces, axis=0)
        seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
        keep = np.concatenate([[True], seg > 1e-9])
        pts = pts[keep]
        cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1])))])
        self.L = float(cum[-1])
        n = int(round(self.L / DS))
        self.q = np.linspace(0.0, self.L, n + 1)
        self.ds = self.L / n
        x = np.interp(self.q, cum, pts[:, 0])
        y = np.interp(self.q, cum, pts[:, 1])
        self.z = np.interp(self.q, cum, pts[:, 2])
        s = SIGMA / self.ds
        self.x = _smooth(x, s)
        self.y = _smooth(y, s)
        self.reverse = reverse
        tx = np.gradient(self.x, self.ds)
        ty = np.gradient(self.y, self.ds)
        travel = np.unwrap(np.arctan2(ty, tx))
        self.heading = travel + (math.pi if reverse else 0.0)  # cap de la voiture
        k = np.gradient(travel, self.ds)
        self.kappa = -k if reverse else k  # courbure vue par la voiture (marche avant)
        d = -WB if reverse else WB
        self.zf = np.interp(np.clip(self.q + d, 0.0, self.L), self.q, self.z)  # sol sous l'essieu avant
        self.sign = -1.0 if reverse else 1.0


# --------------------------------------------------------------------- vitesses
def _S(u):
    return u * u * u * (u * (6 * u - 15) + 10)


def _I(u):
    return u**6 - 3 * u**5 + 2.5 * u**4


def _dS(u):
    return 30 * u * u * (u - 1) ** 2


class Profile:
    """Suite de phases : ('move', distance, vitesse_finale, nom) ou ('hold', durée, nom)."""

    def __init__(self, phases, v0, length):
        self.segs = []  # (t0, dur, q0, dq, va, vb, nom)
        t = q = 0.0
        v = v0
        for ph in phases:
            if ph[0] == "hold":
                assert abs(v) < 1e-9, "arrêt demandé à vitesse non nulle"
                self.segs.append((t, ph[1], q, 0.0, 0.0, 0.0, ph[2]))
                t += ph[1]
            else:
                _, dq, v1, name = ph
                dur = 2 * dq / (v + v1)
                self.segs.append((t, dur, q, dq, v, v1, name))
                t += dur
                q += dq
                v = v1
        self.T = t
        self.v_end = v
        self.Q = q
        # le chemin est une ligne brisée : il est plus court de quelques dixièmes de mm que les arcs exacts
        assert abs(q - length) < 0.02, f"phases {q:.4f} m != chemin {length:.4f} m"

    def at(self, t):
        t = np.asarray(t, dtype=float)
        q = np.zeros_like(t)
        v = np.zeros_like(t)
        a = np.zeros_like(t)
        for t0, dur, q0, dq, va, vb, _ in self.segs:
            m = (t >= t0) & (t <= t0 + dur + 1e-12)
            if not m.any():
                continue
            u = np.clip((t[m] - t0) / dur, 0.0, 1.0)
            q[m] = q0 + va * (t[m] - t0) + (vb - va) * dur * _I(u)
            v[m] = va + (vb - va) * _S(u)
            a[m] = (vb - va) / dur * _dS(u)
        return q, v, a

    def events(self, offset):
        return {name: (offset + t0, offset + t0 + dur) for t0, dur, *_r, name in self.segs if name}


# --------------------------------------------------------------------- la route
def _phases(v_down):
    T = C.TOWER
    hx = C.HERO_X
    up_len = C.R_UP * math.radians(C.TH_END)
    dn_len = C.R_DN * math.radians(C.TH_END)
    xa = C.X_NORTH + C.R_BRIDGE
    q = math.pi / 2
    west = (C.X_NORTH - C.R_TURN) - (hx + C.R_TURN)
    leave = C.PARK_Y - (C.Y_EAST + C.R_TURN)
    east = T[0] - (hx + C.R_TURN)
    mid = [
        ("hold", 1.6, "stop"),
        ("move", C.Y_TAN - Y_STOP, 7.5, "gate_to_ramp"),
        ("move", 12.0, 7.8, "up_a"),
        ("move", up_len - 26.0, 7.8, "up_b"),
        ("move", 14.0, 5.5, "up_c"),
        ("move", T[0] - xa, 3.6, "bridge"),
        ("move", C.R_BRIDGE * q, 3.6, "turn_north"),
        ("move", (C.Y_A2_WEST - C.R_TURN) - (C.Y_WEST + C.R_BRIDGE), 3.6, "north"),
        ("move", C.R_TURN * q, 3.6, "turn_west"),
        ("move", 6.0, 4.8, "west_a"),
        ("move", west - 12.0, 4.8, "west_b"),
        ("move", 6.0, 3.0, "west_c"),
        ("move", C.R_TURN * q, 2.4, "turn_in"),
        ("move", (C.Y_A2_WEST - C.R_TURN) - C.PARK_Y, 0.0, "park"),
        ("hold", DWELL, "parked"),
        ("move", 5.0, 3.6, "leave_a"),
        ("move", leave - 5.0, 3.4, "leave_b"),
        ("move", C.R_TURN * q, 3.6, "turn_east"),
        ("move", 10.0, 6.8, "east_a"),
        ("move", east - 18.0, 6.8, "east_b"),
        ("move", 8.0, v_down, "east_c"),
        ("move", dn_len, v_down, "down"),
        ("move", 7.0, 3.0, "exit_slow"),
    ]
    tail = [("move", 6.0, 3.0, "exit_gate"), ("move", 16.0, V_ROAD, "exit_go")]
    return mid, tail


def _dur(phases, v0):
    t, v = 0.0, v0
    for ph in phases:
        if ph[0] == "hold":
            t += ph[1]
        else:
            t += 2 * ph[1] / (v + ph[2])
            v = ph[2]
    return t


def build(y_hide_in, y_hide_out=None):
    """y_hide_in / y_hide_out : y au sud desquels la voiture qui arrive (phares compris) /
    qui repart est hors de tous les cadres."""
    y_hide_out = y_hide_in if y_hide_out is None else y_hide_out
    T = C.TOWER
    Z = C.ROOF_Z
    hx = C.HERO_X
    brake = 14.0

    # vitesse de descente : règle le décalage entre l'arrêt à l'entrée et le passage à la sortie
    lo, hi = 3.5, 9.0
    for _ in range(60):
        vd = (lo + hi) / 2
        if _dur(_phases(vd)[0], 0.0) > STAGGER:
            lo = vd
        else:
            hi = vd
    mid, tail = _phases(vd)
    fixed = _dur([("move", brake, 0.0, "brake")], V_ROAD) + _dur(mid, 0.0) + _dur(tail, 3.0)
    cruise = (TOTAL - fixed) * V_ROAD  # distance à vitesse de croisière (entrée + sortie)
    y_brake = Y_STOP - brake
    y_go = C.Y_TAN - 7.0 - 6.0 - 16.0
    in_min = y_brake - (y_hide_in - NOSE - 1.0)
    out_min = y_go - (y_hide_out - TAIL - 1.0)
    assert cruise >= in_min + out_min, f"route trop longue : {cruise:.1f} m de croisière pour {in_min + out_min:.1f} m à couvrir"
    extra = (cruise - in_min - out_min) / 2
    d_in, d_out = in_min + extra, out_min + extra

    xa = C.X_NORTH + C.R_BRIDGE
    yb = C.Y_A2_WEST - C.R_TURN
    run = Run(
        [
            _line((C.X_IN, y_brake - d_in), (C.X_IN, C.Y_TAN), 0.0),
            _arc(T, C.R_UP, 0.0, C.TH_END, 0.0, Z),
            _line((T[0], C.Y_WEST), (xa, C.Y_WEST), Z),
            _arc((xa, C.Y_WEST + C.R_BRIDGE), C.R_BRIDGE, 270.0, 180.0, Z),  # à droite, vers le nord
            _line((C.X_NORTH, C.Y_WEST + C.R_BRIDGE), (C.X_NORTH, yb), Z),
            _arc((C.X_NORTH - C.R_TURN, yb), C.R_TURN, 0.0, 90.0, Z),  # à gauche, vers l'ouest
            _line((C.X_NORTH - C.R_TURN, C.Y_A2_WEST), (hx + C.R_TURN, C.Y_A2_WEST), Z),
            _arc((hx + C.R_TURN, yb), C.R_TURN, 90.0, 180.0, Z),  # à gauche, dans la place
            _line((hx, yb), (hx, C.Y_EAST + C.R_TURN), Z),  # arrêt sur la place puis traversée
            _arc((hx + C.R_TURN, C.Y_EAST + C.R_TURN), C.R_TURN, 180.0, 270.0, Z),  # à gauche, vers l'est
            _line((hx + C.R_TURN, C.Y_EAST), (T[0], C.Y_EAST), Z),
            _arc(T, C.R_DN, C.TH_END, 0.0, Z, 0.0),
            _line((C.X_OUT, C.Y_TAN), (C.X_OUT, y_go - d_out), 0.0),
        ]
    )
    phases = [("move", d_in, V_ROAD, "road_in"), ("move", brake, 0.0, "brake")] + mid + tail + [("move", d_out, V_ROAD, "road_out")]
    return Route([run], [Profile(phases, V_ROAD, run.L)])


class Route:
    def __init__(self, runs, profiles):
        self.runs, self.profiles = runs, profiles
        self.T = sum(p.T for p in profiles)
        assert abs(self.T - TOTAL) < 1e-6, f"durée {self.T:.4f} s != {TOTAL} s"
        n = int(round(self.T / DT))
        self.t = np.linspace(0.0, self.T, n + 1)
        cols = {k: np.zeros(n + 1) for k in ("x", "y", "z", "zf", "psi", "kappa", "v", "a")}
        self.events = {}
        t0 = 0.0
        psi_end = None
        for run, prof in zip(self.runs, self.profiles):
            m = (self.t >= t0 - 1e-9) & (self.t <= t0 + prof.T + 1e-9)
            q, v, a = prof.at(np.clip(self.t[m] - t0, 0.0, prof.T))
            head = run.heading
            if psi_end is not None:  # cap continu d'un tronçon au suivant
                head = head + 2 * math.pi * round((psi_end - head[0]) / (2 * math.pi))
            psi_end = head[-1]
            for key, arr in (("x", run.x), ("y", run.y), ("z", run.z), ("zf", run.zf), ("psi", head), ("kappa", run.kappa)):
                cols[key][m] = np.interp(q * (run.L / prof.Q), run.q, arr)
            cols["v"][m] = v * run.sign
            cols["a"][m] = a * run.sign
            self.events.update(prof.events(t0))
            t0 += prof.T
        self.c = cols
        # distance signée parcourue (rotation des roues)
        self.c["dist"] = np.concatenate([[0.0], np.cumsum((cols["v"][1:] + cols["v"][:-1]) / 2 * DT)])
        self.c["steer"] = np.arctan(WB * cols["kappa"])
        self.c["pitch"] = np.arctan2(cols["zf"] - cols["z"], WB)
        # petits mouvements de caisse : cabrage à l'accélération, roulis en virage
        self.c["dpitch"] = np.clip(0.0035 * cols["a"], -0.022, 0.022)
        self.c["droll"] = np.clip(0.0022 * cols["v"] ** 2 * cols["kappa"], -0.028, 0.028)

    def sample(self, tau):
        """État de la voiture à l'instant de route tau (scalaire ou tableau).
        Hors de [0, T] : prolongement en ligne droite (voiture cachée)."""
        tau = np.asarray(tau, dtype=float)
        tc = np.clip(tau, 0.0, self.T)
        out = {k: np.interp(tc, self.t, arr) for k, arr in self.c.items()}
        over = tau - tc  # dépassement (s), à vitesse constante
        v = out["v"]
        out["x"] = out["x"] + over * v * np.cos(out["psi"])
        out["y"] = out["y"] + over * v * np.sin(out["psi"])
        out["dist"] = out["dist"] + over * v
        return out

    def when(self, name, end=False):
        a, b = self.events[name]
        return b if end else a


def corners(st, margin=0.0):
    """Coins au sol de la carrosserie (4 points x, y) pour un état sample() scalaire."""
    c, s = math.cos(float(st["psi"])), math.sin(float(st["psi"]))
    x, y = float(st["x"]), float(st["y"])
    out = []
    for a, b in ((NOSE + margin, HALF_W + margin), (NOSE + margin, -HALF_W - margin), (-TAIL - margin, -HALF_W - margin), (-TAIL - margin, HALF_W + margin)):
        out.append((x + a * c - b * s, y + a * s + b * c))
    return out


if __name__ == "__main__":
    import sys

    r = build(float(sys.argv[1]) if len(sys.argv) > 1 else -88.0, float(sys.argv[2]) if len(sys.argv) > 2 else -76.0)
    print(f"durée totale {r.T:.3f} s")
    for name, (a, b) in sorted(r.events.items(), key=lambda kv: kv[1][0]):
        print(f"  {name:14s} {a:7.3f} -> {b:7.3f}   (boucle {a % C.LOOP:6.3f})")
    c = r.c
    jerk = np.gradient(c["a"], DT)
    yaw = np.degrees(np.gradient(c["psi"], DT))
    step = int(round(1 / (C.FPS * DT)))
    print(f"accél. max {np.abs(c['a']).max():.2f} m/s² ; à-coup max {np.abs(jerk).max():.2f} m/s³ ; lacet max {np.abs(yaw).max():.1f} °/s")
    print(f"saut de cap max entre 2 images : {np.abs(np.diff(np.degrees(c['psi'])[::step])).max():.3f}°")
    print(f"braquage max {np.degrees(np.abs(c['steer']).max()):.1f}° ; accél. latérale max {np.abs(c['v'] ** 2 * c['kappa']).max():.2f} m/s²")
    print(f"y départ {c['y'][0]:.1f} ; y fin {c['y'][-1]:.1f} ; garé en ({np.interp(r.when('parked'), r.t, c['x']):.3f}, {np.interp(r.when('parked'), r.t, c['y']):.3f})")
