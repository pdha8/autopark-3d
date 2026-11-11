"""
Contrôle de la trajectoire (mathématiques pures, sans rendu) :
  - aucune voiture animée n'en touche une autre, ni une voiture garée ;
  - les voitures restent sur la rampe (entre les deux garde-corps) et sur les voies ;
  - dégagements par rapport aux obstacles fixes (îlot du portail, bornes, lampadaires du toit) ;
  - les voitures cachées (début / fin de route) sont bien hors de tous les cadres.

  python scripts/check_route.py        (avec le Python de Blender : numpy requis)
"""

import math
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender"))
import config as C  # noqa: E402
import layout  # noqa: E402
import route as R  # noqa: E402
from camera import View  # noqa: E402

Y_HIDE_IN, Y_HIDE_OUT = -88.0, -76.0
SIZES = {"mini": (0.866, 0.870, 0.455), "sedan": (0.956, 0.956, 0.468), "hatch": (0.886, 0.886, 0.462)}  # avant, arrière, demi-largeur


def rect(x, y, heading_deg, front, back, half):
    c, s = math.cos(math.radians(heading_deg)), math.sin(math.radians(heading_deg))
    return [(x + a * c - b * s, y + a * s + b * c) for a, b in ((front, half), (front, -half), (-back, -half), (-back, half))]


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


def parked_rects():
    rng = random.Random(5)
    out = []
    for s in layout.make():
        dx, dy, da = rng.uniform(-0.13, 0.13), rng.uniform(-0.22, 0.18), rng.uniform(-2.2, 2.2)
        if s["status"] != "occupied" or s["hero"] or s["level"] != C.HERO_LEVEL:
            continue
        f, b, h = (v * C.CAR_SCALE for v in SIZES[s["style"]])
        out.append((s["id"], rect(s["x"] + dx, s["y"] + dy, s["heading"] + da, f, b, h)))
    return out


def main():
    route = R.build(Y_HIDE_IN, Y_HIDE_OUT)
    parked = parked_rects()
    frames = np.arange(C.FRAMES)
    worst = {}

    def note(kind, value, f, detail=""):
        if kind not in worst or value < worst[kind][0]:
            worst[kind] = (value, f, detail)

    posts = [(C.spot_x(c) - C.SPOT_W / 2, 0.0, 0.1) for c in (2, 6, 10, 14)]
    xi = C.ISLAND_X
    fixed = {
        "îlot du portail": [(xi - 0.38, -30.2), (xi + 0.38, -30.2), (xi + 0.38, -23.2), (xi - 0.38, -23.2)],
        "portique (poteau est)": [(C.ROAD_X[1] + 0.3, -24.45), (C.ROAD_X[1] + 0.6, -24.45), (C.ROAD_X[1] + 0.6, -24.15), (C.ROAD_X[1] + 0.3, -24.15)],
        "portique (poteau ouest)": [(C.ROAD_X[0] - 0.6, -24.45), (C.ROAD_X[0] - 0.3, -24.45), (C.ROAD_X[0] - 0.3, -24.15), (C.ROAD_X[0] - 0.6, -24.15)],
    }
    for f in frames:
        t = f / C.FPS
        states = [route.sample(t + k * C.LOOP) for k in range(C.N_CARS)]
        rects = [R.corners(st) for st in states]
        for i in range(C.N_CARS):
            st = states[i]
            x, y, z = float(st["x"]), float(st["y"]), float(st["z"])
            for j in range(i + 1, C.N_CARS):
                if abs(z - float(states[j]["z"])) < 2.2:
                    note("voiture animée / voiture animée", gap(rects[i], rects[j]), f, f"auto{i} auto{j}")
            if z > C.ROOF_Z - 0.3:
                for sid, pr in parked:
                    note("voiture animée / voiture garée (toit)", gap(rects[i], pr), f, f"auto{i} {sid}")
                for px, py, pr_ in posts:
                    g = gap(rects[i], [(px - pr_, py - pr_), (px + pr_, py - pr_), (px + pr_, py + pr_), (px - pr_, py + pr_)])
                    note("voiture animée / lampadaire du toit", g, f, f"auto{i}")
                # rives du toit et de la passerelle
                for cx, cy in rects[i]:
                    if C.BX < cx < C.TOWER[0] and y > C.TOWER[1] + C.R_IN:  # sur la passerelle (pas encore sur la rampe)
                        note("rive de la passerelle", min(cy - (C.TOWER[1] + C.R_IN + 0.1), (C.TOWER[1] + C.R_OUT - 0.1) - cy), f, f"auto{i}")
            if 0.05 < z < C.ROOF_Z - 0.05 or (z <= 0.05 and y > C.Y_TAN - 0.5 and x > C.BX) or (z >= C.ROOF_Z - 0.05 and x > C.TOWER[0]):
                for cx, cy in rects[i]:  # sur la rampe : entre les garde-corps
                    r = math.hypot(cx - C.TOWER[0], cy - C.TOWER[1])
                    if cy > C.Y_TAN - 0.2 or z > 0.3:
                        note("garde-corps de la rampe", min(r - C.R_IN, C.R_OUT - r), f, f"auto{i} r={r:.2f}")
            if z < 0.05 and y < C.Y_TAN:
                for name, poly in fixed.items():
                    note(f"voiture animée / {name}", gap(rects[i], poly), f, f"auto{i}")
                for cx, cy in rects[i]:
                    note("bord de chaussée", min(cx - C.ROAD_X[0], C.ROAD_X[1] - cx), f, f"auto{i}")

    print("Dégagements minimaux sur toute la boucle (m) :")
    ok = True
    for kind, (v, f, d) in sorted(worst.items()):
        flag = "" if v > 0.05 else "   <-- CONTACT"
        ok &= v > 0.05
        print(f"  {kind:42s} {v:6.2f}  (image {f}, {d}){flag}")

    # voitures cachées : hors de tous les cadres au début et à la fin de la route
    for name in C.VIEWS:
        view = View(name)
        for tau, label in ((0.0, "début"), (route.T, "fin")):
            st = route.sample(tau)
            pts = [(cx, cy, zz) for cx, cy in R.corners(st, margin=0.6) for zz in (0.0, 2.2)]
            if tau == 0.0:  # faisceaux des phares
                pts += [(float(st["x"]) + dx, float(st["y"]) + 13.0, 0.0) for dx in (-7.5, 7.5)]
            uv = [view.project(p)[:2] for p in pts]
            inside = any(-0.0 <= u <= 1.0 and 0.0 <= v <= 1.0 for u, v in uv)
            vmax = max(v for _, v in uv)
            print(f"  vue {name:5s} {label:5s} de route : {'VISIBLE !' if inside else 'hors cadre'} (v max = {vmax:.3f})")
            ok &= not inside
    print("RESULTAT :", "OK" if ok else "A CORRIGER")


if __name__ == "__main__":
    main()
