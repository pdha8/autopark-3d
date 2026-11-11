"""
Rendu Blender (Cycles / OptiX) d'AutoPark 3D.

La caméra est fixe : presque toute l'image ne change jamais. On rend donc
  1. un « fond » (plate) une seule fois, très propre, sans les éléments animés ;
  2. pour chaque image, seulement les zones où quelque chose bouge (voitures,
     barrières, ascenseur, lumières qui changent), avec flou de mouvement ;
puis compose.py recolle les zones sur le fond et encode la vidéo.
Résultat : fond parfaitement stable (aucun scintillement) et rendu bien plus rapide.

Exemples :
  blender -b --factory-startup -P blender/render.py -- --view hero --still --frame 150
  blender -b --factory-startup -P blender/render.py -- --view hero --night --anim
  blender -b --factory-startup -P blender/render.py -- --view gate --anim --frames 0-119
"""

import argparse
import json
import math
import os
import sys
import time

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import actors  # noqa: E402
import config as C  # noqa: E402
import route as R  # noqa: E402
import scene as scn  # noqa: E402
import stage  # noqa: E402
import world  # noqa: E402

WORK = os.path.join(HERE, "work")
FEATHER = 14  # largeur du fondu des zones (px)
MARGIN = 10  # marge de sécurité autour des zones (px)


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--view", default="hero", choices=list(C.VIEWS))
    p.add_argument("--night", action="store_true")
    p.add_argument("--still", action="store_true", help="une image complète (aperçu)")
    p.add_argument("--anim", action="store_true", help="fond + zones animées de toute la boucle")
    p.add_argument("--frame", type=int, default=0)
    p.add_argument("--frames", default=None, help="ex. 0-719")
    p.add_argument("--samples", type=int, default=None)
    p.add_argument("--plate-samples", type=int, default=None)
    p.add_argument("--scale", type=float, default=None, help="pixels par unité de maquette (défaut : 1.5 vue générale, 1.25 vues rapprochées)")
    p.add_argument("--out", default=None)
    p.add_argument("--no-cars", action="store_true")
    p.add_argument("--save-blend", action="store_true")
    p.add_argument("--blend", action="store_true", help="construire la scène et l'enregistrer dans blender/scenes/ (sans rendu)")
    p.add_argument("--full", action="store_true", help="avec --anim : images complètes (contrôle), sans zones")
    p.add_argument("--redo-plate", action="store_true")
    return p.parse_args(argv)


# ------------------------------------------------------------------ zones d'influence
def _project(scene, cam, pts):
    rx, ry = scene.render.resolution_x, scene.render.resolution_y
    out = []
    for p in pts:
        co = world_to_camera_view(scene, cam, Vector(p))
        out.append((co.x * rx, co.y * ry))
    return out


def _car_points(route, k, f, night, ev=None):
    """Points du monde qui englobent tout ce qu'une voiture modifie à l'image f :
    carrosserie (avec flou de mouvement), ombre portée, faisceaux des phares la nuit."""
    pts = []
    sun = -stage.KEY_FROM
    for df in (-1.0, 0.0, 1.0):
        st = route.sample((f + df) / C.FPS + k * C.LOOP)
        z0 = min(float(st["z"]), float(st["zf"])) - 0.25
        z1 = max(float(st["z"]), float(st["zf"])) + 2.1
        cs = R.corners(st, margin=0.45)
        for x, y in cs:
            pts.append((x, y, z0))
            pts.append((x, y, z1))
            # ombre du toit sur le sol de la voiture
            s = (z1 - z0) / -sun.z
            pts.append((x + sun.x * s, y + sun.y * s, z0))
        if not night:
            x, y, z = float(st["x"]), float(st["y"]), float(st["z"])
            inside_roof = z > C.ROOF_Z - 0.2 and -C.BX < x < C.BX - 3.5 and -C.BY < y < C.BY - 3.5
            if z > 0.6 and not inside_roof:  # rampe, passerelle : l'ombre peut tomber jusqu'au sol
                s = z1 / -sun.z
                for cx, cy in cs:
                    pts.append((cx + sun.x * s, cy + sun.y * s, 0.0))
        else:
            c, s_ = math.cos(float(st["psi"])), math.sin(float(st["psi"]))
            x, y, z = float(st["x"]), float(st["y"]), float(st["z"])
            # ombres portées par les lampadaires proches (elles s'allongent à l'opposé de la lampe)
            z0 = min(float(st["z"]), float(st["zf"])) - 0.25
            z1 = z0 + 2.3
            for lx, ly, lz in world.LAMP_HEADS:
                if lz < z1 + 1.0 or lz > z1 + 8.0 or math.hypot(lx - x, ly - y) > 9.5:
                    continue
                grow = (lz - z0) / (lz - z1)
                for cx, cy in R.corners(st, margin=0.3):
                    sx, sy = lx + (cx - lx) * grow, ly + (cy - ly) * grow
                    d = math.hypot(sx - cx, sy - cy)
                    if d > 4.0:
                        sx, sy = cx + (sx - cx) * 4.0 / d, cy + (sy - cy) * 4.0 / d
                    pts.append((sx, sy, z0))
            reach = actors.BEAM_REACH + 0.3
            tau = f / C.FPS + k * C.LOOP
            lit = ev is None or float(actors.headlights_on(ev, tau - 1 / C.FPS)) + float(actors.headlights_on(ev, tau + 1 / C.FPS)) > 1e-3
            # cône des phares : demi-angle 25°, éclairage nul au-delà de BEAM_REACH
            for d in (R.NOSE, reach * 0.5, reach) if lit else ():
                half = 0.9 + 0.5 * d
                for side in (-1, 1):
                    px, py = x + d * c - side * half * s_, y + d * s_ + side * half * c
                    pts.append((px, py, z - 0.7))
                    pts.append((px, py, z + 2.9))
    return pts


def _obj_points(ob, pad, depsgraph, night, children=False):
    obs = [ob] + (list(ob.children_recursive) if children else [])
    pts = []
    sun = -stage.KEY_FROM
    for o in obs:
        e = o.evaluated_get(depsgraph)
        if e.type not in ("MESH", "CURVE", "FONT"):
            continue
        mw = e.matrix_world
        for corner in e.bound_box:
            w = mw @ Vector(corner)
            for dx in (-pad, pad):
                for dy in (-pad, pad):
                    pts.append((w.x + dx, w.y + dy, w.z + pad))
                    pts.append((w.x + dx, w.y + dy, w.z - pad))
            if not night and w.z > 0.3:  # ombre jusqu'au sol
                s = w.z / -sun.z
                pts.append((w.x + sun.x * s, w.y + sun.y * s, 0.0))
    return pts


def _rect(scene, cam, pts):
    rx, ry = scene.render.resolution_x, scene.render.resolution_y
    pp = _project(scene, cam, pts)
    pad = FEATHER + MARGIN
    x0 = int(min(p[0] for p in pp)) - pad
    x1 = int(max(p[0] for p in pp)) + pad + 1
    y0 = int(min(p[1] for p in pp)) - pad
    y1 = int(max(p[1] for p in pp)) + pad + 1
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(rx, x1), min(ry, y1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return [x0, y0, x1, y1]


def _merge(rects, limit=8, scale=1.5):
    """Regroupe les zones quand l'union coûte à peine plus de pixels que les deux séparées
    (chaque rendu a un coût fixe d'environ 0,3 s). Deux zones qui se chevauchent un peu
    restent séparées : la partie commune est simplement rendue deux fois."""
    rects = [list(r) for r in rects]

    def area(r):
        return (r[2] - r[0]) * (r[3] - r[1])

    def union(a, b):
        return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]

    budget = 28000 * scale * scale
    while len(rects) > 1:
        best = None
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                u = union(rects[i], rects[j])
                extra = area(u) - area(rects[i]) - area(rects[j])
                if best is None or extra < best[0]:
                    best = (extra, i, j, u)
        extra, i, j, u = best
        if extra > budget and len(rects) <= limit:
            break
        rects = [r for k, r in enumerate(rects) if k not in (i, j)] + [u]
    return rects


def frame_rects(scene, cam, info, f, night):
    """Zones (x0, y0, x1, y1 en pixels, origine en bas à gauche) à rendre pour l'image f."""
    route = info["route"]
    dg = bpy.context.evaluated_depsgraph_get()
    rects = []
    for item in info["registry"]:
        if item["kind"] == "car":
            k = int(item["root"].replace("auto", ""))
            r = _rect(scene, cam, _car_points(route, k, f, night, info["events"]))
        else:
            if not any(a <= f <= b for a, b in item["active"]):
                continue
            if item["kind"] == "box":
                lo, hi = item["min"], item["max"]
                pts = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
            else:
                pts = _obj_points(bpy.data.objects[item["name"]], item.get("pad", 0.5), dg, night, item.get("children", False))
            r = _rect(scene, cam, pts) if pts else None
        if r:
            rects.append(r)
    return _merge(rects, scale=scene.render.resolution_x / C.FRAME_W)


def quiet_frame(info):
    """Image où aucun élément (hors voitures) n'est dans un état particulier : sert de fond."""
    busy = [0] * C.FRAMES
    for item in info["registry"]:
        if item["kind"] == "car" or item.get("children"):
            continue
        for a, b in item["active"]:
            for f in range(a, b + 1):
                busy[f] += 1
    free = [f for f in range(C.FRAMES) if busy[f] == 0]
    assert free, "aucune image de repos pour le fond"
    # milieu de la plus longue plage libre
    runs, start = [], free[0]
    for a, b in zip(free, free[1:] + [None]):
        if b is None or b != a + 1:
            runs.append((start, a))
            start = b
    a, b = max(runs, key=lambda r: r[1] - r[0])
    return (a + b) // 2


def set_border(scene, rect):
    rx, ry = scene.render.resolution_x, scene.render.resolution_y
    r = scene.render
    if rect is None:
        r.use_border = False
        r.use_crop_to_border = False
        return
    r.use_border = True
    r.use_crop_to_border = True
    r.border_min_x = (rect[0] + 0.01) / rx
    r.border_max_x = (rect[2] + 0.01) / rx
    r.border_min_y = (rect[1] + 0.01) / ry
    r.border_max_y = (rect[3] + 0.01) / ry


def hide_dynamic(info, hide):
    for name in ("voitures_animees",):
        bpy.data.collections[name].hide_render = hide
    for item in info["registry"]:
        if item.get("children"):  # cabine d'ascenseur : toujours en mouvement, absente du fond
            ob = bpy.data.objects[item["name"]]
            for o in [ob] + list(ob.children_recursive):
                o.hide_render = hide


# ------------------------------------------------------------------ rendu
def render_anim(scene, info, a, out):
    cam = info["cam"]
    night = a.night
    os.makedirs(os.path.join(out, "zones"), exist_ok=True)
    manifest_path = os.path.join(out, "manifest.json")
    manifest = {"width": scene.render.resolution_x, "height": scene.render.resolution_y, "fps": C.FPS, "frames": C.FRAMES, "night": night, "feather": FEATHER, "zones": {}}
    if os.path.exists(manifest_path) and not a.redo_plate:
        old = json.load(open(manifest_path))
        if old.get("width") == manifest["width"] and old.get("night") == night:
            manifest["zones"] = old.get("zones", {})

    # 1. fond
    plate = os.path.join(out, "plate.png")
    if a.redo_plate or not os.path.exists(plate):
        t0 = time.time()
        hide_dynamic(info, True)
        scene.frame_set(quiet_frame(info))
        scene.render.use_motion_blur = False
        scene.cycles.samples = a.plate_samples or (1400 if night else 700)
        scene.cycles.adaptive_threshold = 0.004
        set_border(scene, None)
        scene.render.filepath = plate
        bpy.ops.render.render(write_still=True)
        hide_dynamic(info, False)
        print(f"FOND rendu en {time.time() - t0:.1f} s (image de repos {scene.frame_current})", flush=True)

    # 2. zones animées
    close = a.view != "hero"
    scene.cycles.samples = a.samples or ((72 if night else 64) if close else (128 if night else 96))
    scene.cycles.adaptive_threshold = 0.012
    scene.render.use_motion_blur = True
    fa, fb = (int(v) for v in a.frames.split("-")) if a.frames else (0, C.FRAMES - 1)
    t0 = time.time()
    done = px = 0
    for f in range(fa, fb + 1):
        key = str(f)
        scene.frame_set(f)
        rects = frame_rects(scene, cam, info, f, night)
        files = [os.path.join(out, "zones", f"{f:04d}_{i}.png") for i in range(len(rects))]
        if key in manifest["zones"] and manifest["zones"][key] == rects and all(os.path.exists(p) for p in files):
            continue
        for rect, path in zip(rects, files):
            set_border(scene, rect)
            scene.render.filepath = path
            bpy.ops.render.render(write_still=True)
            px += (rect[2] - rect[0]) * (rect[3] - rect[1])
        manifest["zones"][key] = rects
        done += 1
        if done % 20 == 0 or f == fb:
            json.dump(manifest, open(manifest_path, "w"))
            el = time.time() - t0
            total = scene.render.resolution_x * scene.render.resolution_y
            print(f"IMAGE {f} : {done} rendues, {el / done:.2f} s/image, {100 * px / done / total:.1f} % du cadre, reste ~{el / done * (fb - f) / 60:.1f} min", flush=True)
    json.dump(manifest, open(manifest_path, "w"))
    set_border(scene, None)
    print(f"ZONES terminées : {done} images en {(time.time() - t0) / 60:.1f} min", flush=True)


def render_full(scene, info, a, out):
    """Images complètes (toute la scène, flou de mouvement) : sert de référence de contrôle."""
    os.makedirs(os.path.join(out, "full"), exist_ok=True)
    scene.cycles.samples = a.samples or 96
    scene.render.use_motion_blur = True
    set_border(scene, None)
    fa, fb = (int(v) for v in a.frames.split("-")) if a.frames else (0, C.FRAMES - 1)
    for f in range(fa, fb + 1):
        scene.frame_set(f)
        scene.render.filepath = os.path.join(out, "full", f"{f:04d}.png")
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        print(f"COMPLETE {f} en {time.time() - t0:.1f} s", flush=True)


def main():
    a = parse_args()
    if a.scale is None:
        a.scale = 1.5 if a.view == "hero" else 1.25
    t0 = time.time()
    scene, info = scn.build(a.night, a.view, a.samples or 64, a.scale, cars=not a.no_cars)
    print(f"SCENE construite en {time.time() - t0:.1f} s ; {len(bpy.data.objects)} objets", flush=True)
    name = f"{a.view}_{'night' if a.night else 'day'}"
    if a.blend:  # scène prête à ouvrir dans Blender (caméra de la vue, animation complète)
        folder = os.path.join(HERE, "scenes")
        os.makedirs(folder, exist_ok=True)
        scene.render.use_motion_blur = True
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(folder, f"{name}.blend"), compress=True)
        print("BLEND", os.path.join(folder, f"{name}.blend"), flush=True)
        return
    if a.still:
        out = os.path.abspath(a.out or os.path.join(WORK, "stills"))
        os.makedirs(out, exist_ok=True)
        if a.save_blend:
            bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, f"{name}.blend"))
        scene.frame_set(a.frame)
        scene.render.filepath = os.path.join(out, f"{name}_{a.frame:04d}.png")
        t1 = time.time()
        bpy.ops.render.render(write_still=True)
        print(f"RENDERED {scene.render.filepath} en {time.time() - t1:.1f} s", flush=True)
        return
    out = os.path.abspath(a.out or os.path.join(WORK, "render", name))
    os.makedirs(out, exist_ok=True)
    if a.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, f"{name}.blend"))
    if a.anim and a.full:
        render_full(scene, info, a, out)
    elif a.anim:
        render_anim(scene, info, a, out)


if __name__ == "__main__":
    main()
