"""
Décor fixe de la maquette AutoPark 3D : socle, bâtiment à 4 niveaux, tour de
rampe hélicoïdale, portail d'entrée/sortie, ascenseur vitré, jardin.
Tout est généré par code (aucun fichier externe).
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

import config as C
import geo
from geo import Geo, circle, rrect

FONT_SIGN = "C:/Windows/Fonts/GOTHICB.TTF"
FONT_DIN = "C:/Windows/Fonts/bahnschrift.ttf"
RAIL_H = 1.05


def _font(path):
    try:
        return bpy.data.fonts.load(path, check_existing=True)
    except Exception:
        return None


def level_z(level):
    return level * C.LEVEL_H


# ------------------------------------------------------------------ socle
def base(M, coll):
    x0, x1, y0, y1 = C.BASE
    g = Geo()
    pts = rrect(x0, x1, y0, y1, 4.0, 8)
    rx0, rx1 = C.ROAD_X[0] - 0.5, C.ROAD_X[1] + 0.5
    pts += [(rx0, y0), (rx0, C.ROAD_END_Y), (rx1, C.ROAD_END_Y), (rx1, y0)]
    g.prism(pts, -C.BASE_T, 0.0)
    g.to_object("socle", coll, M["base"], bevel=0.1, segments=3)

    g = Geo()  # chaussée
    g.box(C.ROAD_X[0], C.ROAD_X[1], C.ROAD_END_Y + 0.4, C.Y_TAN + 1.0, 0.0, 0.03)
    g.to_object("chaussee", coll, M["road"], smooth=False)

    g = Geo()  # dalle du rez-de-chaussée, pied de la tour
    g.box(-C.BX, C.BX, -C.BY, C.BY, 0.0, 0.04)
    g.cyl(C.TOWER[0], C.TOWER[1], 0.0, 0.035, C.R_OUT + 0.5, n=96)
    g.box(C.BX - 0.1, C.TOWER[0], C.TOWER[1] + C.R_IN, C.TOWER[1] + C.R_OUT, 0.0, 0.035)
    g.to_object("dalle_p0", coll, M["deck"], smooth=False)

    g = Geo()  # parvis
    g.prism(rrect(-29.6, 37.9, -30.8, -16.5, 1.6), 0.0, 0.06)
    g.prism(rrect(-29.6, -26.7, -16.6, 19.0, 1.0), 0.0, 0.06)
    g.to_object("parvis", coll, M["paving"], bevel=0.03, segments=2)


def road_markings(M, coll):
    g = Geo()
    z = 0.045
    xc = C.ISLAND_X
    # ligne médiane en tirets, lignes de rive
    y = C.ROAD_END_Y + 2.0
    while y < -34.0:
        g.flat([(xc - 0.09, y), (xc + 0.09, y), (xc + 0.09, y + 2.4), (xc - 0.09, y + 2.4)], z)
        y += 5.0
    for x in (C.ROAD_X[0] + 0.28, C.ROAD_X[1] - 0.28):
        g.flat([(x - 0.07, C.ROAD_END_Y + 1), (x + 0.07, C.ROAD_END_Y + 1), (x + 0.07, C.Y_TAN - 9.0), (x - 0.07, C.Y_TAN - 9.0)], z)
    # ligne d'arrêt devant la lisse d'entrée, flèches
    g.flat([(xc + 0.35, C.GATE_IN_Y - 1.5), (C.ROAD_X[1] - 0.45, C.GATE_IN_Y - 1.5), (C.ROAD_X[1] - 0.45, C.GATE_IN_Y - 1.1), (xc + 0.35, C.GATE_IN_Y - 1.1)], z)
    for x, y0, d in ((C.X_IN, -41.0, 1), (C.X_OUT, -36.0, -1), (C.X_IN, -19.5, 1), (C.X_OUT, -18.0, -1)):
        _arrow(g, x, y0, 90.0 if d > 0 else 270.0, z, 3.2)
    g.to_object("marquage_route", coll, M["mark"], smooth=False)


def _arrow(g, x, y, heading, z, length=2.6, mat=0):
    """Flèche peinte au sol (pointe dans le sens heading, en degrés)."""
    w, hw, hl = 0.16, 0.48, 0.95
    pts = [(-length / 2, -w), (length / 2 - hl, -w), (length / 2 - hl, -hw), (length / 2, 0.0), (length / 2 - hl, hw), (length / 2 - hl, w), (-length / 2, w)]
    c, s = math.cos(math.radians(heading)), math.sin(math.radians(heading))
    g.flat([(x + px * c - py * s, y + px * s + py * c) for px, py in pts], z, mat)


# ------------------------------------------------------------------ bâtiment
COLS_X = [-C.BX + 0.25] + [C.spot_x(c) - C.SPOT_W / 2 for c in range(0, C.NCOL + 1, 3)] + [C.BX - 0.25]
COLS_Y = [-C.BY + 0.25, 0.0, C.BY - 0.25]


def building(M, coll):
    Z = C.ROOF_Z
    g = Geo()  # dalles
    for lv in range(1, C.NLEV):
        z = level_z(lv)
        g.box(-C.BX - 0.25, C.BX + 0.25, -C.BY - 0.25, C.BY + 0.25, z - C.SLAB, z)
    g.box(C.BX + 0.2, C.TOWER[0], C.TOWER[1] + C.R_IN - 0.12, C.TOWER[1] + C.R_OUT + 0.12, Z - C.SLAB, Z)  # passerelle
    g.to_object("dalles", coll, M["concrete"], bevel=0.05, segments=3)

    g = Geo()  # revêtement des niveaux
    for lv in range(1, C.NLEV):
        z = level_z(lv)
        g.box(-C.BX, C.BX, -C.BY, C.BY, z, z + 0.025)
    g.box(C.BX - 0.1, C.TOWER[0], C.TOWER[1] + C.R_IN, C.TOWER[1] + C.R_OUT, Z, Z + 0.025)
    g.to_object("revetement", coll, M["deck"], smooth=False)

    g = Geo()  # poteaux
    for x in COLS_X:
        for y in COLS_Y:
            g.box(x - 0.25, x + 0.25, y - 0.25, y + 0.25, 0.0, Z - C.SLAB + 0.02)
    g.to_object("poteaux", coll, M["concrete"], bevel=0.05, segments=3)

    g = Geo()  # murs nord et ouest (pleins), acrotères du toit
    top = Z + 1.15
    g.box(-C.BX - 0.25, C.BX + 0.25, C.BY, C.BY + 0.25, 0.0, top)
    g.box(-C.BX - 0.25, -C.BX, -C.BY - 0.25, C.BY, 0.0, top)
    g.to_object("murs", coll, M["wall"], bevel=0.04, segments=2)

    g = Geo()  # bordures basses des rives sud et est (tous niveaux) + passerelle
    for lv in range(1, C.NLEV):
        z = level_z(lv)
        g.box(-C.BX, C.BX + 0.25, -C.BY - 0.25, -C.BY - 0.03, z, z + 0.22)
        if lv < C.NLEV - 1:
            g.box(C.BX + 0.03, C.BX + 0.25, -C.BY, C.BY, z, z + 0.22)
        else:  # le toit s'ouvre sur la passerelle
            ya, yb = C.TOWER[1] + C.R_IN - 0.12, C.TOWER[1] + C.R_OUT + 0.12
            g.box(C.BX + 0.03, C.BX + 0.25, -C.BY, ya, z, z + 0.22)
            g.box(C.BX + 0.03, C.BX + 0.25, yb, C.BY, z, z + 0.22)
            g.box(C.BX + 0.25, C.TOWER[0], ya, ya + 0.22, z, z + 0.22)
            g.box(C.BX + 0.25, C.TOWER[0], yb - 0.22, yb, z, z + 0.22)
    g.to_object("bordures", coll, M["concrete"], bevel=0.04, segments=2)

    g = Geo()  # garde-corps métalliques (rives sud et est, passerelle)
    for lv in range(1, C.NLEV):
        z = level_z(lv) + 0.22
        _railing(g, [(-C.BX, -C.BY - 0.14), (C.BX + 0.14, -C.BY - 0.14)], z)
        if lv < C.NLEV - 1:
            _railing(g, [(C.BX + 0.14, -C.BY - 0.14), (C.BX + 0.14, C.BY)], z)
        else:
            ya, yb = C.TOWER[1] + C.R_IN - 0.01, C.TOWER[1] + C.R_OUT + 0.01
            _railing(g, [(C.BX + 0.14, -C.BY - 0.14), (C.BX + 0.14, ya), (C.TOWER[0], ya)], z)
            _railing(g, [(C.TOWER[0], yb), (C.BX + 0.14, yb), (C.BX + 0.14, C.BY)], z)
    g.to_object("garde_corps", coll, M["metal"], smooth=True, weighted=False)

    g = Geo()  # réglettes lumineuses sous les dalles (niveaux couverts)
    for lv in range(1, C.NLEV):
        z = level_z(lv) - C.SLAB
        for ya, yb in (C.AISLE1, C.AISLE2):
            yc = (ya + yb) / 2
            for dy in (-1.6, 1.6):
                x = -C.BX + 3.0
                while x < C.BX - 5.0:
                    g.box(x, x + 4.6, yc + dy - 0.13, yc + dy + 0.13, z - 0.07, z)
                    x += 6.2
        for xc in (-C.BX + 3.0, C.BX - 3.0):  # allées d'extrémité
            y = -C.BY + 2.5
            while y < C.BY - 5.0:
                g.box(xc - 0.13, xc + 0.13, y, y + 4.6, z - 0.07, z)
                y += 6.2
    g.to_object("reglettes", coll, M["ceiling"], smooth=False)


def _railing(g, pts, z, post_every=2.7):
    """Garde-corps fin : poteaux + deux lisses (main courante et lisse intermédiaire)."""
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        n = max(1, round(L / post_every))
        for i in range(n + 1):
            x, y = x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n
            g.box(x - 0.035, x + 0.035, y - 0.035, y + 0.035, z, z + RAIL_H - 0.22)
    for h, r in ((RAIL_H - 0.22, 0.04), (0.45, 0.022), (0.2, 0.022)):
        g.tube([(x, y, z + h) for x, y in pts], r, n=8)


# ------------------------------------------------------------------ places : boucles lumineuses
def _loop_pts(x0, x1, y0, y1):
    inset, w, r = 0.24, 0.11, 0.42
    outer = rrect(x0 + inset, x1 - inset, y0 + inset, y1 - inset, r, 5)
    inner = rrect(x0 + inset + w, x1 - inset - w, y0 + inset + w, y1 - inset - w, r - w, 5)
    return inner, outer


def bay_rect(row, col):
    r = C.ROWS[row]
    x = C.spot_x(col)
    return x - C.SPOT_W / 2, x + C.SPOT_W / 2, r["y0"], r["y1"]


def bay_loops(M, coll, spots, skip=()):
    """Une boucle par place, regroupées par niveau et couleur. skip : places animées à part."""
    groups = {}
    pads = {}
    for s in spots:
        if (s["level"], s["row"], s["col"]) in skip:
            continue
        key = s["status"]
        if s["status"] == "available" and s["type"] != "std":
            key = s["type"]
        z = level_z(s["level"]) + (0.04 if s["level"] == 0 else 0.025) + 0.012
        g = groups.setdefault((s["level"], key), Geo())
        inner, outer = _loop_pts(*bay_rect(s["row"], s["col"]))
        g.band(inner, outer, z)
        if s["type"] != "std":  # tapis de couleur des places spéciales
            p = pads.setdefault(s["type"], Geo())
            x0, x1, y0, y1 = bay_rect(s["row"], s["col"])
            p.flat(rrect(x0 + 0.5, x1 - 0.5, y0 + 0.5, y1 - 0.5, 0.3, 4), z - 0.006)
    for (lv, key), g in groups.items():
        g.to_object(f"boucles_P{lv}_{key}", coll, M[f"led_{key}"], smooth=False)
    for key, p in pads.items():
        p.to_object(f"tapis_{key}", coll, M[f"pad_{key}"], smooth=False)


def single_loop(M, coll, name, level, row, col, mat):
    g = Geo()
    inner, outer = _loop_pts(*bay_rect(row, col))
    g.band(inner, outer, level_z(level) + 0.025 + 0.012)
    return g.to_object(name, coll, mat, smooth=False)


def level_markings(M, coll):
    """Flèches et axes des allées, grand repère de niveau au sol."""
    font = _font(FONT_SIGN)
    for lv in range(C.NLEV):
        z = level_z(lv) + (0.04 if lv == 0 else 0.025) + 0.01
        g = Geo()
        for (ya, yb) in (C.AISLE1, C.AISLE2):
            yc = (ya + yb) / 2
            x = -C.BX + C.END_AISLE + 1.0
            while x < C.BX - C.END_AISLE - 2.0:  # axe en tirets
                g.flat([(x, yc - 0.06), (x + 1.8, yc - 0.06), (x + 1.8, yc + 0.06), (x, yc + 0.06)], z, 1)
                x += 4.05
            for col in (2, 7, 12):
                x = C.spot_x(col)
                _arrow(g, x, yc + 1.5, 180.0, z)
                _arrow(g, x, yc - 1.5, 0.0, z)
        for xc, hd in ((C.BX - 2.2, 90.0), (C.BX - 4.7, 270.0), (-C.BX + 2.2, 270.0), (-C.BX + 4.7, 90.0)):
            _arrow(g, xc, 0.0, hd, z)
        g.to_object(f"marquage_P{lv}", coll, [M["mark"], M["mark_dim"]], smooth=False)
        # repère du niveau, lisible depuis le sud-est
        t = geo.text(f"repere_P{lv}", f"P{lv}", 3.0, coll, M["mark"], font=font)
        geo.place(t, (C.BX - 3.0, 12.4 if lv == C.NLEV - 1 else -13.4, z + 0.004), (0, 0, 0))


# ------------------------------------------------------------------ tour de rampe
def helix_z(theta):
    return C.PITCH * theta / 360.0


def tower(M, coll):
    cx, cy = C.TOWER
    step = 3.0
    n = int(C.TH_END / step)
    thetas = [C.TH_END * i / n for i in range(n + 1)]

    def ring(r, dz):
        return [(cx + r * math.cos(math.radians(t)), cy + r * math.sin(math.radians(t)), helix_z(t) + dz) for t in thetas]

    t_slab = 0.28
    g = Geo()
    g.grid([ring(C.R_IN, 0.0), ring(C.R_OUT, 0.0)], mat=1, flip=True)  # dessus (revêtement)
    g.grid([ring(C.R_IN, -t_slab), ring(C.R_OUT, -t_slab)], mat=0)  # dessous
    g.grid([ring(C.R_OUT, -t_slab), ring(C.R_OUT, 0.0)], mat=0, flip=True)
    g.grid([ring(C.R_IN, -t_slab), ring(C.R_IN, 0.0)], mat=0)
    g.to_object("rampe", coll, [M["concrete"], M["deck"]], smooth=True, weighted=False, angle=50)

    # garde-corps pleins bas + main courante
    ph, pw = 0.62, 0.16
    g = Geo()
    for r0, r1 in ((C.R_OUT, C.R_OUT + pw), (C.R_IN - pw, C.R_IN)):
        g.grid([ring(r0, -t_slab), ring(r0, ph), ring(r1, ph), ring(r1, -t_slab)], mat=0, flip=(r0 < C.R_OUT - 1))
        for t in (thetas[0], thetas[-1]):  # bouchons d'extrémité
            a = math.radians(t)
            pts = [(cx + r * math.cos(a), cy + r * math.sin(a), helix_z(t) + dz) for r, dz in ((r0, -t_slab), (r1, -t_slab), (r1, ph), (r0, ph))]
            g._face([g.bm.verts.new(p) for p in pts], 0)
    g.to_object("rampe_parapets", coll, M["concrete"], smooth=True, weighted=False, angle=50)

    g = Geo()
    for r in (C.R_OUT + pw / 2, C.R_IN - pw / 2):
        g.tube(ring(r, RAIL_H), 0.04, n=8)
        for i in range(0, n + 1, 6):
            t = thetas[i]
            x, y = cx + r * math.cos(math.radians(t)), cy + r * math.sin(math.radians(t))
            g.box(x - 0.03, x + 0.03, y - 0.03, y + 0.03, helix_z(t) + ph, helix_z(t) + RAIL_H)
    g.to_object("rampe_lisses", coll, M["metal"], smooth=True, weighted=False)

    g = Geo()  # bandeau lumineux le long de la rive extérieure
    g.tube(ring(C.R_OUT + pw + 0.02, ph - 0.12), 0.05, n=8)
    g.to_object("rampe_bandeau", coll, M["accent_line"], smooth=True, weighted=False)

    # noyau central
    top = C.ROOF_Z + 2.1
    g = Geo()
    g.cyl(cx, cy, 0.0, top, 2.75, n=96)
    g.cyl(cx, cy, top, top + 0.22, 3.0, n=96)
    g.to_object("noyau", coll, M["core"], bevel=0.05, segments=2, angle=50)

    # grand « P » lumineux et fente de lumière, tournés vers la caméra (sud-est)
    font = _font(FONT_SIGN)
    for ang, kind in ((-52.0, "P"), (-128.0, "slit"), (38.0, "slit")):
        a = math.radians(ang)
        nx, ny = math.cos(a), math.sin(a)
        if kind == "P":
            t = geo.text("noyau_P", "P", 3.0, coll, M["sign_white"], font=font, extrude=0.06)
            # texte debout : X local -> tangente, Y local -> haut, Z local -> normale sortante
            tx, ty = -ny, nx
            m = Matrix(((tx, 0, nx, cx + nx * 2.79), (ty, 0, ny, cy + ny * 2.79), (0, 1, 0, top - 2.6), (0, 0, 0, 1)))
            t.matrix_world = m
        else:
            g = Geo()
            g.box(-0.11, 0.11, -0.03, 0.03, 0.6, top - 0.5)
            ob = g.to_object(f"noyau_fente_{int(ang)}", coll, M["accent_line"], smooth=False)
            ob.location = (cx + nx * 2.77, cy + ny * 2.77, 0)
            ob.rotation_euler = (0, 0, a + math.pi / 2)


# ------------------------------------------------------------------ portail
def gate(M, coll):
    xi = C.ISLAND_X
    font = _font(FONT_SIGN)
    g = Geo()
    g.prism(rrect(xi - 0.38, xi + 0.38, -30.2, -23.2, 0.36, 6), 0.0, 0.2)
    g.to_object("ilot", coll, M["white"], bevel=0.04, segments=2)

    for name, y in (("entree", C.GATE_IN_Y), ("sortie", C.GATE_OUT_Y)):
        g = Geo()
        g.box(xi - 0.27, xi + 0.27, y - 0.24, y + 0.24, 0.2, 1.28)
        ob = g.to_object(f"borne_{name}", coll, M["accent"], bevel=0.07, segments=4)
        g = Geo()
        g.box(xi - 0.285, xi + 0.285, y - 0.255, y + 0.255, 0.98, 1.08)
        g.to_object(f"borne_{name}_bande", coll, M["white"], bevel=0.02, segments=2)

    # caméras de lecture de plaque (ANPR) : une par voie, tournée vers l'avant des voitures
    for name, y, tgt in (("entree", -24.2, (C.X_IN, C.GATE_IN_Y - 2.4, 0.9)), ("sortie", -29.4, (C.X_OUT, C.GATE_OUT_Y + 3.0, 0.9))):
        g = Geo()
        g.cyl(xi, y, 0.2, 2.75, 0.06, n=16)
        g.to_object(f"anpr_{name}_mat", coll, M["metal"], smooth=True, weighted=False)
        head = _anpr_head(M, coll, f"anpr_{name}")
        p = Vector((xi, y, 2.85))
        d = (Vector(tgt) - p).normalized()
        head.matrix_world = Matrix.Translation(p) @ d.to_track_quat("-Y", "Z").to_matrix().to_4x4()

    # portique « ENTRÉE / SORTIE »
    yg = -24.3
    g = Geo()
    for x in (C.ROAD_X[0] - 0.45, C.ROAD_X[1] + 0.45):
        g.cyl(x, yg, 0.0, 5.3, 0.13, n=20)
    g.box(C.ROAD_X[0] - 0.6, C.ROAD_X[1] + 0.6, yg - 0.12, yg + 0.12, 5.05, 5.33)
    g.to_object("portique", coll, M["metal_dark"], bevel=0.03, segments=2)
    for label, x, mat in (("SORTIE", C.X_OUT, "sign_red"), ("ENTRÉE", C.X_IN, "sign_green")):
        g = Geo()
        g.box(x - 1.4, x + 1.4, yg - 0.07, yg + 0.07, 4.12, 5.0)
        g.to_object(f"panneau_{label}", coll, M[mat], bevel=0.05, segments=3)
        t = geo.text(f"texte_{label}", label, 0.52, coll, M["sign_white"], font=font, extrude=0.015)
        geo.place(t, (x, yg - 0.085, 4.56), (90, 0, 0))

    # totem « P »
    tx, ty, rot = 36.9, -29.0, 24.0
    g = Geo()
    g.box(-1.05, 1.05, -0.26, 0.26, 0.0, 7.2)
    tot = g.to_object("totem", coll, M["accent"], bevel=0.2, segments=5)
    tot.location = (tx, ty, 0.06)
    tot.rotation_euler = (0, 0, math.radians(rot))
    p = geo.text("totem_P", "P", 2.3, coll, M["sign_white"], font=font, extrude=0.04)
    p.parent = tot
    geo.place(p, (0, -0.275, 5.75), (90, 0, 0))
    v = geo.text("totem_nom", "AUTOPARK", 0.62, coll, M["sign_white"], font=font, extrude=0.03, spacing=1.12)
    v.parent = tot
    v.matrix_local = Matrix(((0, -1, 0, 0.0), (0, 0, -1, -0.275), (1, 0, 0, 2.45), (0, 0, 0, 1)))


def _anpr_head(M, coll, name):
    """Tête de caméra : objectif vers -Y local."""
    g = Geo()
    g.box(-0.2, 0.2, -0.3, 0.26, -0.12, 0.12)
    g.box(-0.24, 0.24, -0.42, 0.0, 0.12, 0.16)  # visière
    head = g.to_object(name, coll, M["white"], bevel=0.035, segments=3)
    g = Geo()
    g.cyl(0, 0, 0.0, 0.07, 0.085, n=24)
    lens = g.to_object(name + "_objectif", coll, M["car_dark"], smooth=True, weighted=False)
    lens.parent = head
    geo.place(lens, (0, -0.3, 0.0), (90, 0, 0))
    return head


def barrier_arm(M, coll, name, direction):
    """Lisse rayée, origine au pivot. direction = +1 (vers l'est) ou -1 (vers l'ouest)."""
    L = 3.35
    g = Geo()
    n = 7
    for i in range(n):
        a, b = 0.12 + (L - 0.12) * i / n, 0.12 + (L - 0.12) * (i + 1) / n
        g.box(min(direction * a, direction * b), max(direction * a, direction * b), -0.045, 0.045, -0.07, 0.07, mat=i % 2)
    g.box(-0.16, 0.16, -0.07, 0.07, -0.12, 0.12, mat=2)
    arm = g.to_object(name, coll, [M["white"], M["red"], M["metal_dark"]], bevel=0.02, segments=2)
    return arm


# ------------------------------------------------------------------ ascenseur vitré + escalier (angle sud-ouest)
LIFT = {"x0": -30.1, "x1": -26.75, "y0": -15.9, "y1": -12.4}


def lift(M, coll):
    x0, x1, y0, y1 = LIFT["x0"], LIFT["x1"], LIFT["y0"], LIFT["y1"]
    top = C.ROOF_Z + 3.3
    g = Geo()  # ossature
    for x in (x0, x1):
        for y in (y0, y1):
            g.box(x - 0.09, x + 0.09, y - 0.09, y + 0.09, 0.0, top)
    for z in [0.12] + [level_z(lv) for lv in range(1, C.NLEV)] + [top]:
        g.box(x0 - 0.09, x1 + 0.09, y0 - 0.09, y0 + 0.09, z - 0.14, z)
        g.box(x0 - 0.09, x1 + 0.09, y1 - 0.09, y1 + 0.09, z - 0.14, z)
        g.box(x0 - 0.09, x0 + 0.09, y0, y1, z - 0.14, z)
        g.box(x1 - 0.09, x1 + 0.09, y0, y1, z - 0.14, z)
    g.box(x0 - 0.2, x1 + 0.2, y0 - 0.2, y1 + 0.2, top, top + 0.16)
    g.to_object("asc_ossature", coll, M["white"], bevel=0.02, segments=2)
    g = Geo()  # vitrages
    for a, b in (((x0, y0), (x1, y0)), ((x0, y0), (x0, y1)), ((x0, y1), (x1, y1))):
        g.box(min(a[0], b[0]) - 0.012, max(a[0], b[0]) + 0.012, min(a[1], b[1]) - 0.012, max(a[1], b[1]) + 0.012, 0.0, top)
    g.to_object("asc_vitrage", coll, M["glass_blue"], smooth=False)
    g = Geo()  # cage d'escalier
    g.box(x0, x1, y1 + 0.35, y1 + 5.2, 0.0, top - 0.9)
    g.to_object("escalier", coll, M["wall"], bevel=0.06, segments=3)
    g = Geo()
    g.box(x0 + 1.2, x0 + 1.75, y1 + 0.33, y1 + 0.37, 0.8, top - 1.8)
    g.to_object("escalier_fente", coll, M["glass_blue"], smooth=False)


def lift_cabin(M, coll):
    """Cabine (origine au sol de la cabine, au centre)."""
    w, d, h = 2.3, 2.5, 2.55
    g = Geo()
    g.box(-w / 2, w / 2, -d / 2, d / 2, 0.0, 0.12)
    g.box(-w / 2, w / 2, -d / 2, d / 2, h - 0.12, h)
    for x in (-w / 2 + 0.05, w / 2 - 0.05):
        for y in (-d / 2 + 0.05, d / 2 - 0.05):
            g.box(x - 0.05, x + 0.05, y - 0.05, y + 0.05, 0.12, h - 0.12)
    cab = g.to_object("cabine", coll, M["white"], bevel=0.02, segments=2)
    g = Geo()
    g.box(-w / 2 + 0.25, w / 2 - 0.25, -d / 2 + 0.25, d / 2 - 0.25, h - 0.16, h - 0.125)
    lamp = g.to_object("cabine_plafonnier", coll, M["cabin_light"], smooth=False)
    lamp.parent = cab
    g = Geo()
    for x0, x1, y0, y1 in ((-w / 2, w / 2, -d / 2, -d / 2 + 0.02), (-w / 2, -w / 2 + 0.02, -d / 2, d / 2), (-w / 2, w / 2, d / 2 - 0.02, d / 2)):
        g.box(x0, x1, y0, y1, 0.12, h - 0.12)
    gl = g.to_object("cabine_vitres", coll, M["glass"], smooth=False)
    gl.parent = cab
    cab.location = ((LIFT["x0"] + LIFT["x1"]) / 2, (LIFT["y0"] + LIFT["y1"]) / 2, 0.14)
    return cab


# ------------------------------------------------------------------ jardin, mobilier
def _tree(M, coll, name, x, y, h=4.2, r=1.7, seed=0):
    g = Geo()
    g.cyl(x, y, 0.0, h * 0.62, 0.16, n=10, r_top=0.11)
    g.to_object(name + "_tronc", coll, M["trunk"], smooth=True, weighted=False)
    bm = bmesh.new()
    blobs = [(0.0, 0.0, h * 0.72, r), (0.55 * r, 0.25 * r, h * 0.9, r * 0.72), (-0.5 * r, -0.2 * r, h * 0.86, r * 0.66), (0.1 * r, -0.45 * r, h * 1.0, r * 0.6)]
    for i, (dx, dy, z, rr) in enumerate(blobs):
        a = math.radians(seed * 67 + i * 40)
        ddx, ddy = dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)
        bmesh.ops.create_icosphere(bm, subdivisions=3, radius=rr, matrix=Matrix.Translation((x + ddx, y + ddy, z)))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(M["leaf_a" if seed % 2 == 0 else "leaf_b"])
    for p in me.polygons:
        p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def landscape(M, coll):
    g = Geo()
    lawns = [(-25.6, -11.5, -29.6, -19.6), (-7.6, 9.4, -29.6, -19.6), (13.4, 31.5, -29.6, -19.6), (-30.2, 37.5, 17.7, 19.9), (48.3, 51.9, -30.8, 19.6), (27.5, 46.6, 0.6, 16.4)]
    for x0, x1, y0, y1 in lawns:
        g.prism(rrect(x0, x1, y0, y1, 1.2, 6), 0.0, 0.2)
    g.to_object("pelouses", coll, M["lawn"], bevel=0.07, segments=3)

    g = Geo()  # haies basses
    for x0, x1, y0, y1 in ((-25.0, -12.1, -19.1, -18.2), (-7.0, 8.8, -19.1, -18.2), (14.0, 26.0, -19.1, -18.2), (48.7, 49.7, -30.0, -2.0)):
        g.prism(rrect(x0, x1, y0, y1, 0.42, 5), 0.2, 1.05)
    g.to_object("haies", coll, M["hedge"], bevel=0.16, segments=4)

    trees = [(-22.0, -25.6, 4.6, 1.9), (-15.0, -24.0, 3.8, 1.5), (-3.5, -25.4, 4.4, 1.8), (5.0, -24.2, 3.7, 1.5), (17.5, -25.6, 4.5, 1.8), (27.0, -24.3, 3.9, 1.6), (50.1, 6.0, 4.4, 1.7), (50.1, 14.0, 3.8, 1.5), (-20.0, 18.8, 4.2, 1.6), (-4.0, 18.8, 4.6, 1.8), (12.0, 18.8, 4.0, 1.6), (30.0, 18.8, 4.4, 1.7), (36.0, 8.5, 5.0, 2.1), (42.5, 4.0, 4.0, 1.6), (33.0, 13.0, 3.8, 1.5)]
    for i, (x, y, h, r) in enumerate(trees):
        _tree(M, coll, f"arbre_{i}", x, y, h, r, seed=i)

    g = Geo()  # potelets lumineux le long du parvis
    gl = Geo()
    x = -28.0
    while x < 36.5:
        g.cyl(x, -31.3, 0.0, 0.62, 0.11, n=14)
        gl.cyl(x, -31.3, 0.62, 0.7, 0.115, n=14)
        x += 3.6
    g.to_object("potelets", coll, M["metal_dark"], smooth=True, weighted=False)
    gl.to_object("potelets_led", coll, M["accent_line"], smooth=True, weighted=False)


LAMP_HEADS = []  # positions des sources (remplie par lamps) : sert au calcul des ombres la nuit
STREET_LAMPS = [(-9.6, -24.6, 180), (11.3, -24.6, 0), (30.5, -30.0, 0), (48.2, -29.6, 180)]
ROOF_LAMPS = [C.spot_x(c) - C.SPOT_W / 2 for c in (2, 6, 10, 14)]


def lamps(M, coll, night):
    g, gl = Geo(), Geo()
    heads = []
    for x, y, rot in STREET_LAMPS:
        s = -1 if rot == 180 else 1
        g.cyl(x, y, 0.0, 5.0, 0.08, n=12, r_top=0.06)
        g.box(min(x, x + s * 1.3), max(x, x + s * 1.3), y - 0.05, y + 0.05, 4.94, 5.04)
        g.box(min(x + s * 0.8, x + s * 1.75), max(x + s * 0.8, x + s * 1.75), y - 0.17, y + 0.17, 4.9, 5.0)
        gl.box(min(x + s * 0.85, x + s * 1.7), max(x + s * 0.85, x + s * 1.7), y - 0.13, y + 0.13, 4.86, 4.9)
        heads.append((x + s * 1.3, y, 4.8, 800))
    z = C.ROOF_Z
    for x in ROOF_LAMPS:
        g.cyl(x, 0.0, z, z + 5.2, 0.08, n=12, r_top=0.06)
        g.box(x - 0.06, x + 0.06, -1.5, 1.5, z + 5.12, z + 5.22)
        for s in (-1, 1):
            g.box(x - 0.17, x + 0.17, min(s * 0.9, s * 1.85), max(s * 0.9, s * 1.85), z + 5.08, z + 5.18)
            gl.box(x - 0.13, x + 0.13, min(s * 0.95, s * 1.8), max(s * 0.95, s * 1.8), z + 5.04, z + 5.08)
            heads.append((x, s * 1.4, z + 5.0, 720))
    LAMP_HEADS[:] = [(x, y, zz) for x, y, zz, _p in heads]
    g.to_object("lampadaires", coll, M["metal_dark"], bevel=0.015, segments=2)
    gl.to_object("lampadaires_led", coll, M["street"], smooth=False)
    if night:
        for i, (x, y, zz, power) in enumerate(heads):
            li = bpy.data.lights.new(f"lampadaire_{i}", "SPOT")
            li.energy = power
            li.spot_size = math.radians(125)
            li.spot_blend = 0.6
            li.shadow_soft_size = 0.2
            li.color = (1.0, 0.86, 0.66)
            ob = bpy.data.objects.new(li.name, li)
            coll.objects.link(ob)
            ob.location = (x, y, zz)


def ev_chargers(M, coll, spots):
    """Bornes de recharge au fond des places EV (rez-de-chaussée, côté façade)."""
    g, gs = Geo(), Geo()
    for s in spots:
        if s["type"] != "ev":
            continue
        x = s["x"] + C.SPOT_W / 2
        y = C.ROWS[s["row"]]["y0"] + 0.32
        g.box(x - 0.17, x + 0.17, y - 0.12, y + 0.12, 0.04, 1.32)
        gs.box(x - 0.11, x + 0.11, y - 0.135, y - 0.12, 0.92, 1.18)
    g.to_object("bornes_ev", coll, M["white"], bevel=0.04, segments=3)
    gs.to_object("bornes_ev_ecran", coll, M["screen"], smooth=False)


def build_static(M, coll, spots, night, skip_loops=()):
    base(M, coll)
    road_markings(M, coll)
    building(M, coll)
    bay_loops(M, coll, spots, skip=skip_loops)
    level_markings(M, coll)
    tower(M, coll)
    gate(M, coll)
    lift(M, coll)
    landscape(M, coll)
    lamps(M, coll, night)
    ev_chargers(M, coll, spots)
