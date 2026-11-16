"""
Contrôle de la circulation (mathématiques pures, sans rendu) :
  - aucun véhicule en mouvement n'en touche un autre, ni une voiture garée ;
  - chacun reste sur la rampe (entre les garde-corps), sur les passerelles, sur la chaussée ;
  - dégagements par rapport aux obstacles fixes (îlot du portail, portique, poteaux,
    lampadaires du toit, murs et rives des niveaux) ;
  - les lisses sont levées quand un véhicule passe dessous ;
  - les véhicules qui entrent ou sortent par la route le font hors de tous les cadres ;
  - nombre de véhicules en circulation à chaque instant.

  python scripts/check_route.py        (avec le Python de Blender : numpy requis)
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender"))
import config as C  # noqa: E402
import route as R  # noqa: E402
import sim  # noqa: E402
import traffic  # noqa: E402
from camera import View  # noqa: E402

T = C.TOWER
STEP = 2  # une image sur deux


def gap(a, b):
    """Distance entre deux polygones convexes (négative s'ils se recouvrent), par axes séparateurs."""
    best = -1e9
    for poly in (a, b):
        n = len(poly)
        for i in range(n):
            ex, ey = poly[(i + 1) % n][0] - poly[i][0], poly[(i + 1) % n][1] - poly[i][1]
            L = math.hypot(ex, ey)
            nx, ny = ey / L, -ex / L
            pa = [p[0] * nx + p[1] * ny for p in a]
            pb = [p[0] * nx + p[1] * ny for p in b]
            best = max(best, min(pb) - max(pa), min(pa) - max(pb))
    return best


def square(x, y, h):
    return [(x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h)]


def window(t, t_on, t_off, rise, fall):
    S = lambda u: (lambda u: u * u * u * (u * (6 * u - 15) + 10))(min(1.0, max(0.0, u)))
    t_on, t_off = t_on % C.LOOP, t_off % C.LOOP
    if t_off < t_on:
        t_off += C.LOOP
    return sum(S((t + j * C.LOOP - t_on) / rise) - S((t + j * C.LOOP - t_off) / fall) for j in (-1, 0, 1))


def main():
    fleet = traffic.plan(verbose=False)
    worst = {}

    def note(kind, value, t, detail=""):
        if kind not in worst or value < worst[kind][0]:
            worst[kind] = (value, t, detail)

    # --- véhicules entre eux et avec les voitures garées (emprises, toute la boucle)
    pairs = sim.verify(fleet.occ)
    print("Plus petits écarts entre véhicules (m) :")
    for (a, b), (g, tt) in pairs[:10]:
        print(f"  {g:5.2f}  {a} / {b}  (t = {tt:.1f} s)")
    ok = not pairs or pairs[0][1][0] >= 0.15

    # --- obstacles fixes
    xi = C.ISLAND_X
    ground = {
        "îlot du portail": [(xi - 0.38, -30.2), (xi + 0.38, -30.2), (xi + 0.38, -23.2), (xi - 0.38, -23.2)],
        "portique (poteau est)": square(C.ROAD_X[1] + 0.45, -24.3, 0.15),
        "portique (poteau ouest)": square(C.ROAD_X[0] - 0.45, -24.3, 0.15),
    }
    roof_posts = [square(C.spot_x(c) - C.SPOT_W / 2, 0.0, 0.1) for c in (2, 6, 10, 14)]
    cols_x = [-C.BX + 0.25] + [C.spot_x(c) - C.SPOT_W / 2 for c in range(0, C.NCOL + 1, 3)] + [C.BX - 0.25]
    pillars = [square(x, y, 0.25) for x in cols_x for y in (-C.BY + 0.25, 0.0, C.BY - 0.25)]
    ins = [(c, c.at("gate") + 0.8 if c.gate == "stop" else c.at("anpr") + 0.2, c.at("in_clear")) for c in fleet.chains if c.has("in_clear")]
    outs = [(c, c.at("out_ramp"), c.at("out_clear")) for c in fleet.chains if c.has("out_clear")]
    counts = []
    ya, yb = T[1] + C.R_IN + 0.1, T[1] + C.R_OUT - 0.1
    for f in range(0, C.FRAMES, STEP):
        t = f / C.FPS
        moving = 0
        arm_in = min(1.0, sum(window(t, a, b, 0.7, 0.9) for _c, a, b in ins))
        arm_out = min(1.0, sum(window(t, a, b, 0.7, 0.9) for _c, a, b in outs))
        for chain, k in fleet.cars():
            tau = float(chain.tau(t, k))
            if tau > chain.trip.T:
                continue
            st = chain.trip.sample(tau)
            d = chain.d
            x, y, z = float(st["x"]), float(st["y"]), float(st["z"])
            moving += abs(float(st["v"])) > 0.05
            rect = R.corners(st, d)
            who = f"{chain.name}#{k}"
            r_axle = math.hypot(x - T[0], y - T[1])
            on_level = any(abs(z - traffic.LZ(lv)) < 0.05 for lv in range(C.NLEV)) and x < C.BX + 0.3
            on_bridge = C.BX < x < T[0] and z > 6.0 and (abs(y - C.Y_WEST) < 0.5 or abs(y - C.Y_EAST) < 0.5)
            if z < 0.3 and y < C.Y_TAN - 0.5:  # route d'accès et portail
                for name, poly in ground.items():
                    note(f"véhicule / {name}", gap(rect, poly), t, who)
                for cx, cy in rect:
                    note("bord de chaussée", min(cx - C.ROAD_X[0], C.ROAD_X[1] - cx), t, who)
                nose_y = y + d.nose * math.sin(float(st["psi"]))
                tail_y = y - d.tail * math.sin(float(st["psi"]))
                if x > xi and min(nose_y, tail_y) < C.GATE_IN_Y < max(nose_y, tail_y):
                    note("lisse d'entrée levée (0 à 1)", arm_in, t, who)
                if x < xi and min(nose_y, tail_y) < C.GATE_OUT_Y < max(nose_y, tail_y):
                    note("lisse de sortie levée (0 à 1)", arm_out, t, who)
            elif on_bridge:
                for cx, cy in rect:
                    if C.BX < cx < T[0] and math.hypot(cx - T[0], cy - T[1]) > C.R_OUT:
                        note("rive des passerelles", min(cy - ya, yb - cy), t, who)
            elif on_level:
                for cx, cy in rect:
                    if cx < C.BX:
                        note("murs et rives des niveaux", min(cx + C.BX, cy + C.BY, C.BY - cy), t, who)
                    if cx > C.BX - 0.4 and not (ya - 0.3 < cy < yb + 0.3):
                        note("rive est des niveaux", C.BX - cx, t, who)
                if z > C.ROOF_Z - 0.3:
                    for p in roof_posts:
                        note("véhicule / lampadaire du toit", gap(rect, p), t, who)
                else:
                    for p in pillars:
                        note("véhicule / poteau", gap(rect, p), t, who)
            elif r_axle < C.R_OUT + 0.5:  # sur la rampe : entre les garde-corps
                for cx, cy in rect:
                    r = math.hypot(cx - T[0], cy - T[1])
                    note("garde-corps de la rampe", min(r - C.R_IN, C.R_OUT - r), t, f"{who} r = {r:.2f}")
        counts.append(moving)

    print("Dégagements minimaux sur toute la boucle (m) :")
    for kind, (v, t, d) in sorted(worst.items()):
        low = 0.75 if "lisse" in kind else 0.05
        flag = "" if v > low else "   <-- A CORRIGER"
        ok &= v > low
        print(f"  {kind:36s} {v:6.2f}  (t = {t:5.1f} s, {d}){flag}")

    # --- entrées et sorties par la route : hors de tous les cadres
    for chain in fleet.chains:
        ends = [(0.0, "début")] if chain.has("in_clear") else []
        ends += [(chain.trip.T, "fin")] if chain.has("out_clear") else []
        for tau, label in ends:
            st = chain.trip.sample(tau)
            pts = [(cx, cy, zz) for cx, cy in R.corners(st, chain.d, margin=0.6) for zz in (0.0, 2.6)]
            if tau == 0.0:  # faisceaux des phares
                pts += [(float(st["x"]) + dx, float(st["y"]) + 13.0, 0.0) for dx in (-7.5, 7.5)]
            for name in C.VIEWS:
                uv = [View(name).project(p)[:2] for p in pts]
                if any(0.0 <= u <= 1.0 and 0.0 <= v <= 1.0 for u, v in uv):
                    print(f"  {chain.name} : {label} de trajet VISIBLE dans la vue {name}")
                    ok = False
    n = len(fleet.cars())
    print(f"Flotte : {len(fleet.chains)} chaînes, {n} véhicules ; en mouvement : min {min(counts)}, moyenne {sum(counts) / len(counts):.1f}, max {max(counts)}")
    print("RESULTAT :", "OK" if ok else "A CORRIGER")


if __name__ == "__main__":
    main()
