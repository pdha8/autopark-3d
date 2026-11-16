"""
Circulation d'AutoPark 3D (numpy seul) : construit le trajet de chaque chaîne de la
flotte (fleet.py), puis les cadence une à une avec le simulateur (sim.py).

Voies (circulation à droite) :
  route d'accès     entrée x = X_IN (vers le nord), sortie x = X_OUT (vers le sud)
  rampe             montée par la voie extérieure, descente par la voie intérieure
  passerelles       toit et niveau P2 : arrivée y = YW (vers l'ouest), départ y = YE (vers l'est)
  allée sud         YW vers l'ouest, YE vers l'est ; allée nord : YW2 vers l'ouest
  tour du toit      allée d'extrémité est (vers le nord) -> allée nord -> extrémité ouest -> allée sud
On entre dans une place par un virage à gauche depuis la voie opposée, ou par un
déport à gauche suivi d'un virage à droite ; on en sort en marche arrière.
"""

import hashlib
import json
import math
import os
import time

import numpy as np

import config as C
import fleet as F
import layout
from carspecs import dims
from route import Leg, Run, Trip, arc, fillet, line
from sim import DRIVERS, Jam, Occupancy, clearance, simulate, verify

T = C.TOWER
YW, YE, YW2 = C.Y_WEST, C.Y_EAST, C.Y_A2_WEST
XN, XSW = C.X_NORTH, -C.X_NORTH
Z0 = 0.02
Y_START, Y_END = -104.0, -98.0  # début et fin de route : hors de tous les cadres
STOP_GAP = 1.2  # distance nez -> lisse à l'arrêt
V_ROAD = 8.5
TH_P2 = 450.0  # la rampe passe devant la passerelle du niveau P2 après 1 tour 1/4
X_P2_HIDE = 16.0  # au niveau P2, à l'ouest de cette abscisse, l'allée sud est invisible de l'extérieur
Z_P2 = C.PITCH * TH_P2 / 360.0


def LZ(level):
    """Altitude de roulage d'un niveau."""
    return level * C.LEVEL_H + (0.035 if level == 0 else 0.02)


def spur_z(x, y):
    """Sol de la passerelle du niveau P2 : surface de la rampe dans l'anneau, puis plan incliné
    jusqu'à la rive du niveau."""
    dx, dy = x - T[0], y - T[1]
    if math.hypot(dx, dy) <= C.R_OUT:
        return C.PITCH * (math.degrees(math.atan2(dy, dx)) % 360.0 + 360.0) / 360.0
    xe = T[0] - math.sqrt(max(C.R_OUT**2 - dy * dy, 0.0))
    ze = C.PITCH * (math.degrees(math.atan2(dy, xe - T[0])) % 360.0 + 360.0) / 360.0
    u = min(1.0, max(0.0, (xe - x) / max(xe - C.BX, 1e-6)))
    return ze + (LZ(2) - ze) * u


def _zfun(x, y, z):
    return spur_z(x, y) if (C.BX - 0.01 < x < T[0] and 6.0 < z < 9.0) else z


def bay_pose(row, col, d):
    """Centre de la place en x, ordonnée de l'essieu arrière une fois garé, nez au sud ?"""
    r = C.ROWS[row]
    yc = (r["y0"] + r["y1"]) / 2
    south = r["heading"] == 270.0
    return C.spot_x(col), (yc + d.axle_y if south else yc - d.axle_y), south


def _caps(run, drv):
    f = drv["speed"]
    x, y, z = run.x, run.y, run.z
    cap = np.full(len(x), 4.0 * f)  # niveaux et passerelles
    cap[np.hypot(x - T[0], y - T[1]) < C.R_OUT] = 5.2 * f  # rampe : c'est le virage qui limite
    ground = z < 0.5
    cap[ground & (y < -36.0)] = V_ROAD * f
    cap[ground & (y >= -36.0) & (x > C.ISLAND_X)] = 4.2 * f  # portail, voie d'entrée
    cap[ground & (y >= -36.0) & (y < C.Y_TAN - 3.0) & (x < C.ISLAND_X)] = 3.2 * f  # voie de sortie
    run.cap = np.minimum(run.cap, cap)
    return run


def _in(th_end, z_end):
    return [line((C.X_IN, Y_START), (C.X_IN, C.Y_TAN), Z0), arc(T, C.R_UP, 0.0, th_end, Z0, z_end)]


def _out(th_start, z_start):
    return [arc(T, C.R_DN, th_start, 0.0, z_start, Z0), line((C.X_OUT, C.Y_TAN), (C.X_OUT, Y_END), Z0)]


def _gate_in(trip, li, run, d, drv, gate):
    """Arrêt (ou passage au pas) à la barrière d'entrée ; repères pour la barrière et la caméra."""
    q_stop = (C.GATE_IN_Y - STOP_GAP - d.nose) - Y_START
    trip.mark("anpr", li, q_stop - 2.0)  # passage au pas : la plaque est lue juste avant la lisse
    trip.mark("in_clear", li, (C.GATE_IN_Y + d.tail + 1.0) - Y_START)
    trip.mark("ramp", li, C.Y_TAN - Y_START)
    if gate == "stop":
        return [(q_stop, drv.get("gate_hold", 1.6), "gate")]
    run.limit(2.3, q_stop - 3.5, q_stop + 5.0)
    return []


def _gate_out(trip, li, run, d):
    trip.mark("out_ramp", li, run.L - (C.Y_TAN - Y_END) + 0.4)
    trip.mark("out_gate", li, run.L - ((C.GATE_OUT_Y + d.nose + 3.0) - Y_END))
    trip.mark("out_clear", li, run.L - ((C.GATE_OUT_Y - d.tail - 1.0) - Y_END))


def _back(bx, ya, th0, a, rr, phi, z, d):
    """Marche arrière : recul droit de a mètres (sens th0), puis arc de rayon rr sur phi degrés
    (positif : l'arrière part à gauche du sens de marche). Renvoie le tronçon et la pose finale."""
    t0 = math.radians(th0)
    ux, uy = math.cos(t0), math.sin(t0)
    p1 = (bx + ux * a, ya + uy * a)
    sgn = 1.0 if phi > 0 else -1.0
    cen = (p1[0] - uy * rr * sgn, p1[1] + ux * rr * sgn)
    a0 = th0 - 90.0 * sgn
    run = Run([line((bx, ya), p1, z), arc(cen, rr, a0, a0 + phi, z)], d.wb, reverse=True)
    run.limit(1.5)
    a1 = math.radians(a0 + phi)
    return run, (cen[0] + rr * math.cos(a1), cen[1] + rr * math.sin(a1), (th0 + phi + 180.0) % 360.0)


# --------------------------------------------------------------------- trajets
def trip_roof(d, drv, gate, row, col, enter, leave, dwell):
    z = LZ(3)
    bx, ya, south = bay_pose(row, col, d)
    p0 = (T[0], YW)
    if enter == "left" and row == 2:
        pts = [p0, (XN, YW, C.R_BRIDGE), (XN, YW2, 4.0), (bx, YW2, 4.0), (bx, ya)]
    elif enter == "left" and row == 0:
        pts = [p0, (bx, YW, 4.0), (bx, ya)]
    elif enter == "swing" and row == 1:  # déport vers le sud, puis à droite dans la place
        pts = [p0, (bx + 12.5, YW, 8.0), (bx + 6.5, YW - 2.3, 8.0), (bx, YW - 2.3, 3.6), (bx, ya)]
    elif enter == "swing" and row == 3:
        pts = [p0, (XN, YW, C.R_BRIDGE), (XN, YW2, 4.0), (bx + 12.5, YW2, 8.0), (bx + 6.5, YW2 - 2.1, 8.0), (bx, YW2 - 2.1, 3.6), (bx, ya)]
    else:
        raise ValueError(f"entrée {enter} impossible en rangée {row}")
    trip = Trip([], d, v0=V_ROAD * drv["speed"])
    run = _caps(Run(_in(C.TH_END, z) + fillet(pts, z), d.wb), drv)
    run.limit(2.2, run.L - 7.0).limit(1.5, run.L - 2.2)
    trip.legs.append(Leg(run, _gate_in(trip, 0, run, d, drv, gate), end=(dwell, "parked", True), name="aller"))
    q_roof = (C.Y_TAN - Y_START) + C.R_UP * math.radians(C.TH_END)
    trip.mark("roof", 0, q_roof)
    if enter == "left" and row == 2:  # chevrons de guidage : de l'entrée de l'allée nord au virage vers la place
        q_w = q_roof + (T[0] - (XN + C.R_BRIDGE)) + C.R_BRIDGE * math.pi / 2 + ((YW2 - 4.0) - (YW + C.R_BRIDGE)) + 4.0 * math.pi / 2
        trip.mark("guide_a", 0, q_w)
        trip.mark("guide_b", 0, run.L - ((YW2 - 4.0) - ya))
    if leave == "through":  # repart en marche avant à travers la place d'en face (rangée B)
        out = _caps(Run(fillet([(bx, ya), (bx, YE, 4.0), (T[0], YE)], z) + _out(C.TH_END, z), d.wb), drv)
        out.limit(2.6, 0.0, 11.0)
        trip.legs.append(Leg(out, name="retour"))
        trip.mark("bay_clear", 1, d.tail + 0.15 + ya)
        trip.mark("pass_in", 1, ya - (d.nose - 0.4))
        trip.mark("pass_out", 1, ya + C.SPOT_D + d.tail - 0.3)
    else:
        th0 = 90.0 if south else 270.0
        lane = {0: YE, 1: YE, 2: YW2, 3: YW2}[row]  # voie rejointe après la marche arrière
        if leave == "back90":  # quart de tour : finit dans l'axe de la voie
            rev, (px, py, h1) = _back(bx, ya, th0, abs(lane - ya) - 3.2, 3.2, -90.0, z, d)
        else:  # recule en pivotant de 65°, puis repart en biais
            rev, (px, py, h1) = _back(bx, ya, th0, 2.6, 3.4, 65.0, z, d)
        trip.legs.append(Leg(rev, end=(0.9, "backed", False), name="recul"))
        tan25 = math.tan(math.radians(25.0))
        if leave == "back90" and row == 1:  # face à l'est, dans l'allée sud
            pts = [(px, py), (T[0], YE)]
        elif leave == "back90" and row == 2:  # face à l'ouest, dans l'allée nord : tour par l'ouest
            pts = [(px, py), (XSW, YW2, 4.0), (XSW, YE, 4.0), (T[0], YE)]
        elif leave == "back65" and row == 3:  # se redresse avant la voie (le nez ne déborde pas sur les places)
            yj = YW2 - 0.8
            qx = px - (yj - py) / tan25
            pts = [(px, py), (qx, yj, 4.0), (qx - 3.0, yj, 8.0), (qx - 9.0, YW2, 8.0), (XSW, YW2, 4.0), (XSW, YE, 4.0), (T[0], YE)]
        elif leave == "back65" and row == 0:
            yj = YE + 0.8
            qx = px + (py - yj) / tan25
            pts = [(px, py), (qx, yj, 4.0), (qx + 3.0, yj, 8.0), (qx + 9.0, YE, 8.0), (T[0], YE)]
        else:
            raise ValueError(f"sortie {leave} impossible en rangée {row}")
        out = _caps(Run(fillet(pts, z) + _out(C.TH_END, z), d.wb), drv)
        out.limit(2.4, 0.0, 6.0)
        trip.legs.append(Leg(out, name="retour"))
    _gate_out(trip, len(trip.legs) - 1, trip.legs[-1].run, d)
    return trip


def trip_loop(d, drv, gate, stop_x, hold):
    """Taxi : tour complet du toit, dépose dans l'allée nord, puis sortie."""
    z = LZ(3)
    pts = [(T[0], YW), (XN, YW, C.R_BRIDGE), (XN, YW2, 4.0), (XSW, YW2, 4.0), (XSW, YE, 4.0), (T[0], YE)]
    trip = Trip([], d, v0=V_ROAD * drv["speed"])
    run = _caps(Run(_in(C.TH_END, z) + fillet(pts, z) + _out(C.TH_END, z), d.wb), drv)
    q_roof = (C.Y_TAN - Y_START) + C.R_UP * math.radians(C.TH_END)
    stops = _gate_in(trip, 0, run, d, drv, gate) + [(run.q_at("x", stop_x, start=q_roof + 30.0), hold, "drop")]
    trip.legs.append(Leg(run, stops, name="tour"))
    trip.mark("roof", 0, q_roof)
    _gate_out(trip, 0, run, d)
    return trip


def trip_p2_in(d, drv, gate):
    z = LZ(2)
    pieces = _in(TH_P2, Z_P2) + [line((T[0], YW), (C.BX, YW), Z_P2, z), line((C.BX, YW), (X_P2_HIDE, YW), z)]
    trip = Trip([], d, v0=V_ROAD * drv["speed"])
    run = _caps(Run(pieces, d.wb, zfun=_zfun), drv)
    trip.legs.append(Leg(run, _gate_in(trip, 0, run, d, drv, gate), name="aller"))
    return trip


def trip_p2_out(d, drv, gate=None):
    z = LZ(2)
    pieces = [line((X_P2_HIDE - 1.0, YE), (C.BX, YE), z), line((C.BX, YE), (T[0], YE), z, Z_P2)] + _out(TH_P2, Z_P2)
    trip = Trip([], d, v0=3.0)
    run = _caps(Run(pieces, d.wb, zfun=_zfun), drv)
    trip.legs.append(Leg(run, name="retour"))
    _gate_out(trip, 0, run, d)
    return trip


def trip_visit(d, drv, gate=None, level=1, col=5, dwell=12.0):
    """Niveau couvert : vient de l'allée (cachée), se gare en façade sud, repart en marche arrière."""
    z = LZ(level)
    bx, ya, _south = bay_pose(0, col, d)
    bx += {0: 0.15, 2: -0.15}.get(col % 3, 0.0)  # un poteau borde la place : on se gare un peu à l'écart
    trip = Trip([], d, v0=3.0)
    run = _caps(Run(fillet([(bx + 7.5, YW), (bx, YW, 4.0), (bx, ya)], z), d.wb), drv)
    run.limit(2.2, run.L - 7.0).limit(1.5, run.L - 2.2)
    trip.legs.append(Leg(run, end=(dwell, "parked", True), name="aller"))
    rev, (px, py, _h) = _back(bx, ya, 90.0, (YW - 3.4) - ya, 3.4, -90.0, z, d)  # finit face à l'ouest
    trip.legs.append(Leg(rev, end=(0.9, "backed", False), name="recul"))
    trip.legs.append(Leg(_caps(Run([line((px, py), (max(px - 11.0, -C.BX + 5.5), YW), z)], d.wb), drv), name="retour"))
    return trip


TRIPS = {"roof": trip_roof, "loop": trip_loop, "p2_in": trip_p2_in, "p2_out": trip_p2_out, "visit": trip_visit}


# --------------------------------------------------------------------- la flotte cadencée
class Chain:
    def __init__(self, spec, d, drv, trip, m):
        self.spec, self.d, self.drv, self.trip, self.m = spec, d, drv, trip, m
        self.name, self.style, self.paint, self.plate = spec["name"], spec["style"], spec["paint"], spec["plate"]
        self.t0, self.kind, self.gate = spec["t0"], spec["trip"], spec.get("gate")
        a = spec["args"]
        self.bay = (C.HERO_LEVEL, a["row"], a["col"]) if self.kind == "roof" else (a["level"], 0, a["col"]) if self.kind == "visit" else None

    def tau(self, t, k):
        """Instant du trajet du véhicule k à l'instant t de la boucle."""
        return np.mod(np.asarray(t, dtype=float) + k * C.LOOP - self.t0, self.m * C.LOOP)

    def state(self, t, k):
        return self.trip.sample(self.tau(t, k))

    def at(self, name):
        """Instant d'un événement dans la boucle (il s'y produit une fois par tour)."""
        return (self.t0 + self.trip.events[name]) % C.LOOP

    def has(self, name):
        return name in self.trip.events


class Fleet:
    def __init__(self, chains, occ):
        self.chains, self.occ = chains, occ
        self.by_name = {c.name: c for c in chains}

    def cars(self):
        return [(c, k) for c in self.chains for k in range(c.m)]


_PLAN = None
MIN_GAP = 0.2  # écart minimal toléré entre deux carrosseries (m)
MAX_DELAY = 9.0  # retard maximal accepté par rapport au trajet sans gêne (s)
_SOURCES = ("config.py", "carspecs.py", "layout.py", "fleet.py", "route.py", "sim.py", "traffic.py")


def _cache_path():
    here = os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha1()
    for name in _SOURCES:
        h.update(open(os.path.join(here, name), "rb").read())
    return os.path.join(here, "work", f"plan_{h.hexdigest()[:12]}.json")


def plan(verbose=False, cache=True):
    """Cadence toute la flotte. Pour chaque chaîne, dans l'ordre de priorité, on cherche l'horaire
    d'entrée le plus proche de celui demandé qui passe sans contact ni retard excessif.
    Le résultat est gardé en cache (blender/work) tant que les sources ne changent pas."""
    global _PLAN
    if _PLAN is not None:
        return _PLAN
    path = _cache_path()
    saved = json.load(open(path)) if cache and os.path.exists(path) else None
    occ = Occupancy()
    for car in layout.parked_cars(layout.make()):
        occ.add_static(car["x"], car["y"], math.radians(car["heading"]), dims(car["style"]), car["z"], car["id"])
    chains, store = [], []
    for i, spec in enumerate(F.FLEET):
        d = dims(spec["style"])
        drv = dict(DRIVERS[spec["drv"]])
        trip = TRIPS[spec["trip"]](d, drv, spec.get("gate"), **spec["args"])
        name = spec["name"]
        clock, tries = time.time(), 0
        if saved is not None:
            sv = saved[i]
            t0, m, free, gap = sv["t0"], sv["m"], sv["free"], (sv["gap"], "", 0.0)
            trip.set_motion(np.array(sv["t"]), np.array(sv["leg"]), np.array(sv["q"]), sv["events"], [tuple(p) for p in sv["parked"]])
            trip.log = []
            occ.add_trip(trip, t0, m, name)
        else:
            free = simulate(trip, drv, 0.0, None, name).T
            limit = free + spec.get("max_delay", MAX_DELAY)
            why = []
            for step in range(int(C.LOOP / 0.75)):
                t0 = (spec["t0"] + 0.75 * ((step + 1) // 2) * (1 if step % 2 else -1)) % C.LOOP
                tries += 1
                try:
                    simulate(trip, drv, t0, occ, name, t_max=limit, wait_max=25.0)
                except Jam as e:
                    why.append(str(e))
                    continue
                m = int(math.ceil((trip.T + 0.5) / C.LOOP))
                cols = occ.add_trip(trip, t0, m, name)
                gap = clearance(occ, cols)
                if gap[0] >= MIN_GAP:
                    break
                why.append(f"t0 = {t0:.2f} : {gap[0]:.2f} m entre {gap[1]} à t = {gap[2]:.1f} s")
                occ.pop(cols)
            else:
                raise RuntimeError(f"aucun horaire possible pour {name} :" + "".join(chr(10) + "  " + w for w in why[:14]))
        spec = dict(spec, t0=t0)
        chains.append(Chain(spec, d, drv, trip, m))
        t, lg, q = trip.raw
        store.append({"t0": t0, "m": m, "free": free, "gap": gap[0], "t": [round(float(x), 3) for x in t], "leg": [int(x) for x in lg], "q": [round(float(x), 4) for x in q], "events": trip.events, "parked": trip.parked})
        if verbose:
            stuck = sorted({w.split("#")[0] for _t, _l, _q, w in trip.log if w})
            print(f"  {name:17s} t0 {t0:5.2f}  {trip.T:6.1f} s (retard {trip.T - free:4.1f})  x{m}  écart min {gap[0]:.2f} m" + (f"  cède à : {', '.join(stuck)}" if stuck else "") + f"   [{tries} essai(s), {time.time() - clock:.1f} s]", flush=True)
    if saved is None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(store, open(path, "w"))
    _PLAN = Fleet(chains, occ)
    return _PLAN


if __name__ == "__main__":
    import sys

    t = time.time()
    fl = plan(verbose=True, cache="--force" not in sys.argv)
    print(f"{len(fl.chains)} chaînes, {len(fl.cars())} véhicules, cadencés en {time.time() - t:.1f} s")
    pairs = verify(fl.occ)
    for (a, b), (g, tt) in pairs[:14]:
        print(f"  écart {g:5.2f} m  {a} / {b}  (t = {tt:.1f} s)")
    print("CONTACTS :", sum(1 for _k, (g, _t) in pairs if g < 0.03))
