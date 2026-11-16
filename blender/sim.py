"""
Simulateur de circulation (numpy seul) : cadence un trajet le long de son chemin en
tenant compte des véhicules déjà planifiés.

Chaque véhicule suit sa vitesse de consigne (zones, virages, freinage anticipé avant
un arrêt) et regarde devant lui : il n'avance que si, en freinant ensuite
normalement, il ne touche personne — ou s'il a le temps de dégager le passage.
Il s'arrête donc derrière une file, cède le passage avant de couper une voie,
attend qu'une manœuvre se termine, puis repart. Les autres véhicules sont connus
sur toute la boucle (positions périodiques) : le résultat est exactement périodique.
"""

import math

import numpy as np

import config as C

BIN = 0.1  # pas de la table d'occupation (s)
DT = 0.1  # pas de simulation (s)
LA = 0.25  # pas de l'anticipation (s)
H_GO, H_STOP = 5.0, 8.0  # horizons : « je continue » / « je m'arrête et j'attends »

DRIVERS = {
    "calme": {"speed": 0.88, "acc": 1.15, "brake": 1.35, "a_lat": 1.7, "gap": 1.7, "headway": 0.9},
    "normal": {"speed": 1.0, "acc": 1.5, "brake": 1.7, "a_lat": 2.0, "gap": 1.4, "headway": 0.75},
    "vif": {"speed": 1.1, "acc": 1.9, "brake": 2.0, "a_lat": 2.35, "gap": 1.2, "headway": 0.65},
}


class Jam(Exception):
    """Le véhicule n'arrive pas à passer (bouchon, attente trop longue) : essayer un autre horaire."""


class Occupancy:
    """Emprises au sol (rectangles orientés) de tous les véhicules, par tranche de temps de la boucle."""

    def __init__(self, kmax=420):
        self.nb = int(round(C.LOOP / BIN))
        self.a = {k: np.zeros((self.nb, kmax)) for k in ("cx", "cy", "ux", "uy", "hl", "hw", "z")}
        self.kind = np.zeros((self.nb, kmax), dtype=np.int8)  # 0 : absent, 1 : en circulation, 2 : garé
        self.labels = []
        self.n = self.n_static = 0

    def _put(self, k, x, y, psi, d, z, kind):
        off = (d.nose - d.tail) / 2
        a = self.a
        a["cx"][:, k], a["cy"][:, k] = x + off * np.cos(psi), y + off * np.sin(psi)
        a["ux"][:, k], a["uy"][:, k] = np.cos(psi), np.sin(psi)
        a["hl"][:, k], a["hw"][:, k], a["z"][:, k] = d.length / 2, d.half_w, z
        self.kind[:, k] = kind

    def add_static(self, x, y, heading, d, z, label):
        """Voiture garée fixe (x, y : centre du modèle ; heading en radians)."""
        self._put(self.n, x - d.axle_y * math.cos(heading), y - d.axle_y * math.sin(heading), heading, d, z, 2)
        self.labels.append(label)
        self.n += 1
        self.n_static = self.n

    def add_trip(self, trip, t0, m, label):
        tb = np.arange(self.nb) * BIN
        first = self.n
        for k in range(m):
            tau = np.mod(tb + k * C.LOOP - t0, m * C.LOOP)
            st = trip.sample(tau)
            kind = np.where(st["on"] > 0, np.where(trip.is_parked(tau), 2, 1), 0)
            self._put(self.n, st["x"], st["y"], st["psi"], trip.d, st["z"], kind)
            self.labels.append(f"{label}#{k}")
            self.n += 1
        return list(range(first, self.n))

    def pop(self, cols):
        """Retire les dernières colonnes ajoutées (essai d'horaire refusé)."""
        assert cols and cols[-1] == self.n - 1
        self.kind[:, cols] = 0
        del self.labels[cols[0] :]
        self.n = cols[0]

    def near(self, trip, reach=9.0):
        """Colonnes à surveiller pour un trajet : toute la flotte, et les voitures fixes proches du chemin."""
        px = np.concatenate([lg.run.x[::20] for lg in trip.legs])
        py = np.concatenate([lg.run.y[::20] for lg in trip.legs])
        pz = np.concatenate([lg.run.z[::20] for lg in trip.legs])
        a = self.a
        ns = self.n_static
        d2 = (a["cx"][0, :ns, None] - px[None, :]) ** 2 + (a["cy"][0, :ns, None] - py[None, :]) ** 2
        ok = (d2 < reach * reach) & (np.abs(a["z"][0, :ns, None] - pz[None, :]) < 2.0)
        return np.concatenate([np.nonzero(ok.any(axis=1))[0], np.arange(ns, self.n)]).astype(int)

    def gaps(self, bins, cols, cx, cy, ux, uy, hl, hw):
        """Écart (négatif : recouvrement) entre des rectangles propres (N,) et les colonnes cols (N, K)."""
        ix = np.ix_(bins, cols)
        A = {k: v[ix] for k, v in self.a.items()}
        dx, dy = A["cx"] - cx[:, None], A["cy"] - cy[:, None]
        best = np.full(dx.shape, -1e9)
        for ax, ay in ((ux[:, None], uy[:, None]), (-uy[:, None], ux[:, None]), (A["ux"], A["uy"]), (-A["uy"], A["ux"])):
            own = hl[:, None] * np.abs(ux[:, None] * ax + uy[:, None] * ay) + hw[:, None] * np.abs(-uy[:, None] * ax + ux[:, None] * ay)
            oth = A["hl"] * np.abs(A["ux"] * ax + A["uy"] * ay) + A["hw"] * np.abs(-A["uy"] * ax + A["ux"] * ay)
            best = np.maximum(best, np.abs(dx * ax + dy * ay) - own - oth)
        return best, A["z"], self.kind[ix]


def _blocked(occ, cols, run, d, drv, t_abs, q, v, taus):
    """Le véhicule, aux abscisses q (vitesses v) aux instants t_abs + taus, gêne-t-il quelqu'un ?
    Renvoie l'étiquette du premier gêneur, ou None.
    Voitures garées : marge fine autour de la carrosserie. Circulation : la carrosserie et la
    distance de sécurité devant elle, portée le long du chemin (elle suit donc les virages)."""
    if not len(cols):
        return None
    st = run.at(q)
    bins = np.mod(np.round((t_abs + taus) / BIN).astype(int), occ.nb)
    ix = np.ix_(bins, cols)
    kd = occ.kind[ix]
    close = (kd > 0) & (np.abs(occ.a["z"][ix] - st["z"][:, None]) < 2.0) & ((occ.a["cx"][ix] - st["x"][:, None]) ** 2 + (occ.a["cy"][ix] - st["y"][:, None]) ** 2 < 256.0)
    if not close.any():
        return None
    sub = cols[close.any(axis=0)]
    lead = drv["gap"] + drv["headway"] * np.abs(v)
    tests = [(2, q, 0.25, 0.2, 0.1)] + [(1, np.minimum(q + f * lead, run.L), 0.3, 0.3, 0.2) for f in (0.0, 0.5, 1.0)]
    for kind, qs, front, back, side in tests:
        s2 = st if qs is q else run.at(qs)
        ux, uy = np.cos(s2["heading"]), np.sin(s2["heading"])
        f, b = (d.nose + front, d.tail + back) if not run.reverse else (d.nose + back, d.tail + front)
        off = (f - b) / 2
        g, z, k2 = occ.gaps(bins, sub, s2["x"] + off * ux, s2["y"] + off * uy, ux, uy, np.full_like(ux, (f + b) / 2), np.full_like(ux, d.half_w + side))
        bad = (g < 0) & (k2 == kind) & (np.abs(z - s2["z"][:, None]) < 2.0)
        if bad.any():
            return occ.labels[sub[np.argwhere(bad)[0][1]]]
    return None


def simulate(trip, drv, t0, occ, label="", t_max=400.0, wait_max=60.0):
    """Cadence le trajet (départ à l'instant t0 de la boucle). Renvoie trip, complété.
    Lève Jam si le trajet dépasse t_max ou si une attente dépasse wait_max."""
    d = trip.d
    acc, brake, a_lat = drv["acc"], drv["brake"], drv["a_lat"]
    cols = occ.near(trip) if occ is not None and occ.n else np.zeros(0, dtype=int)
    T, Lg, Q = [], [], []
    events, parked = {}, []
    t, v = 0.0, trip.v0
    waited = 0.0
    trip.log = []  # (instant, tronçon, abscisse, gêneur) à chaque changement : mise au point
    last = None
    for li, leg in enumerate(trip.legs):
        run = leg.run
        stops = [(q, h, n, False) for q, h, n in leg.stops]
        if leg.end is not None:
            stops.append((run.L, leg.end[0], leg.end[1], leg.end[2]))
        q, si = 0.0, 0
        T.append(t), Lg.append(li), Q.append(q)
        prof = run.profile(a_lat, brake, stops[si][0] if si < len(stops) else None)
        hold = 0.0
        while True:
            if hold > 0:  # à l'arrêt (barrière, dépose, stationnement, changement de sens)
                hold -= DT
                t += DT
                T.append(t), Lg.append(li), Q.append(q)
                if hold <= 1e-9:
                    q_s, _h, name, park = stops[si]
                    events[name + "_end"] = t
                    if park:
                        parked[-1] = (parked[-1][0], t)
                    si += 1
                    if q_s >= run.L - 1e-6:
                        break
                    prof = run.profile(a_lat, brake, stops[si][0] if si < len(stops) else None)
                continue
            q_stop = stops[si][0] if si < len(stops) else None
            lim = run.L if q_stop is None else q_stop
            v_des = float(np.interp(min(q + v * DT, lim), run.q, prof))
            if q_stop is not None:  # fin d'approche : on avance au pas jusqu'au point d'arrêt
                v_des = max(v_des, min(0.3, 0.5 * (lim - q) / DT))
            v_go = min(v + acc * DT, v_des) if v_des >= v else max(v_des, v - 1.5 * brake * DT)
            q1 = min(q + (v + v_go) / 2 * DT, lim)
            # 1. j'avance d'un pas puis je freine et j'attends : sans risque ?
            taus = DT + np.arange(0.0, H_STOP + 1e-9, LA)
            ts = np.minimum(taus - DT, v_go / brake)
            qb = np.minimum(q1 + v_go * ts - 0.5 * brake * ts**2, lim)
            vb = np.maximum(v_go - brake * (taus - DT), 0.0)
            who = _blocked(occ, cols, run, d, drv, t0 + t, qb, vb, taus)
            if who is not None and lim - q > 0.5:
                # 2. sinon : en continuant sur ma lancée, ai-je dégagé le passage à temps ?
                qa, va, qq, vv = [], [], q1, v_go
                for _ in range(int(H_GO / LA)):
                    vd = float(np.interp(min(qq + vv * LA, lim), run.q, prof))
                    vn = min(vv + acc * LA, vd) if vd >= vv else max(vd, vv - 1.5 * brake * LA)
                    qq = min(qq + (vv + vn) / 2 * LA, lim)
                    vv = vn
                    qa.append(qq), va.append(vv)
                # « dégager » n'a de sens que si l'on finit ailleurs que derrière le gêneur
                if (qa[-1] - q) > d.length + 2.0 and _blocked(occ, cols, run, d, drv, t0 + t, np.array(qa), np.array(va), DT + LA * (1 + np.arange(len(qa)))) is None:
                    who = None
            if who != last:
                trip.log.append((round(t, 1), li, round(q, 1), who))
                last = who
            if who is None:
                q, v = q1, v_go
                waited = 0.0
            else:
                v_new = max(0.0, v - brake * DT)
                q = min(q + (v + v_new) / 2 * DT, lim)
                v = v_new
                if v == 0.0:
                    waited += DT
                    if waited > wait_max:
                        raise Jam(f"{label} : bloqué plus de {wait_max:.0f} s par {who} (tronçon {li}, q = {q:.1f} m, t = {t:.1f} s)")
            t += DT
            if t > t_max:
                raise Jam(f"{label} : trajet trop long (tronçon {li}, q = {q:.1f} / {run.L:.1f} m, t = {t:.1f} s)")
            T.append(t), Lg.append(li), Q.append(q)
            if q_stop is not None and q >= q_stop - 0.03 and v < 0.35:
                q, v = q_stop, 0.0
                Q[-1] = q
                _q, h, name, park = stops[si]
                events[name] = t
                if park:
                    parked.append((t, t + h))
                hold = max(h, DT)
            elif q_stop is None and q >= run.L - 1e-6:
                break
    return trip.set_motion(np.array(T), np.array(Lg), np.array(Q), events, parked)


def clearance(occ, cols):
    """Écart minimal (dimensions réelles) entre les colonnes cols et tout le reste, et l'endroit."""
    A, best = occ.a, (9.9, "", 0.0)
    for k in cols:
        on = np.nonzero(occ.kind[:, k] == 1)[0]
        if not len(on):
            continue
        others = np.array([c for c in range(occ.n) if c != k])
        g, z, kd = occ.gaps(on, others, A["cx"][on, k], A["cy"][on, k], A["ux"][on, k], A["uy"][on, k], A["hl"][on, k], A["hw"][on, k])
        g = np.where((kd > 0) & (np.abs(z - A["z"][on, k][:, None]) < 2.0), g, 9.9)
        i, j = np.unravel_index(np.argmin(g), g.shape)
        if g[i, j] < best[0]:
            best = (float(g[i, j]), f"{occ.labels[k]} / {occ.labels[others[j]]}", on[i] * BIN)
    return best


def verify(occ, limit=1.0):
    """Écarts minimaux entre véhicules en mouvement et tous les autres, par couple, sur la boucle."""
    worst = {}
    A = occ.a
    for k in range(occ.n_static, occ.n):
        on = np.nonzero(occ.kind[:, k] == 1)[0]
        if not len(on):
            continue
        others = np.array([c for c in range(occ.n) if c != k])
        g, z, kd = occ.gaps(on, others, A["cx"][on, k], A["cy"][on, k], A["ux"][on, k], A["uy"][on, k], A["hl"][on, k], A["hw"][on, k])
        g = np.where((kd > 0) & (np.abs(z - A["z"][on, k][:, None]) < 2.0), g, 9.9)
        for j in np.nonzero(g.min(axis=0) < limit)[0]:
            key = tuple(sorted((occ.labels[k], occ.labels[others[j]])))
            i = int(np.argmin(g[:, j]))
            if key not in worst or g[i, j] < worst[key][0]:
                worst[key] = (float(g[i, j]), on[i] * BIN)
    return sorted(worst.items(), key=lambda kv: kv[1][0])
