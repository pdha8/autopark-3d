"""
Aperçu schématique de la circulation, vue de dessus (sans Blender : numpy + ffmpeg).
Sert à juger la chorégraphie avant de lancer un rendu : quelques secondes de calcul.

  python scripts/topview.py [sortie.mp4] [images par seconde]     (Python de Blender)

À gauche : tout le site (couleur du contour = niveau). À droite : le toit, puis le niveau P2.
"""

import math
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender"))
import config as C  # noqa: E402
import layout  # noqa: E402
import traffic  # noqa: E402
from carspecs import dims  # noqa: E402

W, H = 1280, 720
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender", "work", "topview.mp4")
FPS = int(sys.argv[2]) if len(sys.argv) > 2 else 20

# panneau : (x0, y0 pixels, largeur, hauteur, xmin, xmax monde, ymin monde, filtre z)
PANELS = [
    (0, 0, 520, 720, -30.0, 54.0, -98.0, None),
    (520, 0, 760, 400, -29.0, 49.0, -19.0, (C.ROOF_Z - 0.6, 99.0)),
    (520, 400, 760, 320, -29.0, 49.0, -17.5, (7.0, 9.0)),
]


def hex_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.uint8)


def paint_rgb(paint):
    if paint == "hero":
        return hex_rgb(C.ACCENT)
    return hex_rgb(paint) if isinstance(paint, str) else hex_rgb(C.PAINTS[paint][1])


def to_px(panel, x, y):
    px0, py0, pw, ph, xmin, xmax, ymin, _z = panel
    s = pw / (xmax - xmin)
    return px0 + (x - xmin) * s, py0 + ph - (y - ymin) * s


def fill(img, panel, pts, color):
    """Remplit un polygone convexe (points du monde) dans le panneau."""
    px0, py0, pw, ph = panel[:4]
    P = np.array([to_px(panel, x, y) for x, y in pts])
    x0, x1 = max(px0, int(P[:, 0].min())), min(px0 + pw - 1, int(P[:, 0].max()) + 1)
    y0, y1 = max(py0, int(P[:, 1].min())), min(py0 + ph - 1, int(P[:, 1].max()) + 1)
    if x1 <= x0 or y1 <= y0:
        return
    gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
    inside = np.ones(gx.shape, dtype=bool)
    sign = None
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        cr = (b[0] - a[0]) * (gy - a[1]) - (b[1] - a[1]) * (gx - a[0])
        if sign is None:
            sign = 1.0 if ((P[2][0] - a[0]) * (b[1] - a[1]) - (P[2][1] - a[1]) * (b[0] - a[0])) < 0 else -1.0
        inside &= cr * sign >= 0
    img[y0 : y1 + 1, x0 : x1 + 1][inside] = color


def box(x, y, psi, d, grow=0.0):
    c, s = math.cos(psi), math.sin(psi)
    return [(x + a * c - b * s, y + a * s + b * c) for a, b in ((d.nose + grow, d.half_w + grow), (d.nose + grow, -d.half_w - grow), (-d.tail - grow, -d.half_w - grow), (-d.tail - grow, d.half_w + grow))]


def level_color(z):
    if z > C.ROOF_Z - 0.6:
        return (255, 255, 255)
    if 7.0 < z < 9.0:
        return (120, 220, 255)
    return (255, 200, 90) if z > 0.6 else (40, 40, 48)


def background():
    img = np.full((H, W, 3), (26, 30, 40), dtype=np.uint8)
    for panel in PANELS:
        fill(img, panel, [(-C.BX, -C.BY), (C.BX, -C.BY), (C.BX, C.BY), (-C.BX, C.BY)], (52, 58, 70))
        fill(img, panel, [(C.ROAD_X[0], -98), (C.ROAD_X[1], -98), (C.ROAD_X[1], C.Y_TAN), (C.ROAD_X[0], C.Y_TAN)], (40, 44, 54))
        ring = [(C.TOWER[0] + C.R_OUT * math.cos(a), C.TOWER[1] + C.R_OUT * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 48, endpoint=False)]
        fill(img, panel, ring, (46, 51, 62))
        core = [(C.TOWER[0] + C.R_IN * math.cos(a), C.TOWER[1] + C.R_IN * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 32, endpoint=False)]
        fill(img, panel, core, (26, 30, 40))
        fill(img, panel, [(C.BX, C.Y_EAST - 1.7), (C.TOWER[0], C.Y_EAST - 1.7), (C.TOWER[0], C.Y_WEST + 1.9), (C.BX, C.Y_WEST + 1.9)], (52, 58, 70))
        fill(img, panel, [(C.ISLAND_X - 0.4, -30.2), (C.ISLAND_X + 0.4, -30.2), (C.ISLAND_X + 0.4, -23.2), (C.ISLAND_X - 0.4, -23.2)], (200, 200, 200))
        zf = panel[7]
        for car in layout.parked_cars(layout.make()):
            if zf is None or zf[0] < car["z"] + 0.5 < zf[1] + 0.5:
                if zf is None and car["level"] != C.HERO_LEVEL:
                    continue
                d = dims(car["style"])
                h = math.radians(car["heading"])
                fill(img, panel, box(car["x"] - d.axle_y * math.cos(h), car["y"] - d.axle_y * math.sin(h), h, d), (92, 99, 112))
    return img


def main():
    fleet = traffic.plan(verbose=False)
    bg = background()
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", OUT]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(C.LOOP * FPS)
    counts = []
    for i in range(n):
        t = i / FPS
        img = bg.copy()
        moving = 0
        for chain, k in fleet.cars():
            tau = float(chain.tau(t, k))
            if tau > chain.trip.T:
                continue
            st = chain.trip.sample(tau)
            x, y, z, psi = (float(st[key]) for key in ("x", "y", "z", "psi"))
            moving += abs(float(st["v"])) > 0.05
            for panel in PANELS:
                zf = panel[7]
                if zf is not None and not (zf[0] < z < zf[1]):
                    continue
                fill(img, panel, box(x, y, psi, chain.d, 0.25), level_color(z))
                fill(img, panel, box(x, y, psi, chain.d), paint_rgb(chain.paint))
                c, s = math.cos(psi), math.sin(psi)
                nose = [(x + a * c - b * s, y + a * s + b * c) for a, b in ((chain.d.nose, 0.5), (chain.d.nose, -0.5), (chain.d.nose - 0.9, -0.5), (chain.d.nose - 0.9, 0.5))]
                fill(img, panel, nose, (20, 22, 28))
        counts.append(moving)
        bar = int(W * i / n)
        img[H - 4 :, :bar] = (90, 160, 255)
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    proc.wait()
    print(f"APERCU {OUT} ; véhicules en mouvement : min {min(counts)}, moyenne {sum(counts) / len(counts):.1f}, max {max(counts)}")


if __name__ == "__main__":
    main()
