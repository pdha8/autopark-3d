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
  blender -b --factory-startup -P blender/render.py -- --view hero --anim --step 4 --scale 0.5 --samples 24 --out aperçu
"""

import argparse
import hashlib
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
RENDERS = os.path.join(WORK, f"render-{int(C.LOOP)}s")  # un dossier par durée de boucle
SCENE_SOURCES = ("config", "carspecs", "cars", "layout", "fleet", "route", "sim", "traffic", "world", "geo", "mats", "stage", "camera", "actors", "anim", "scene")


def scene_key():
    """Empreinte du code qui construit la scène : un rendu commencé avec un autre code est refait."""
    h = hashlib.sha1()
    for name in SCENE_SOURCES:
        h.update(open(os.path.join(HERE, name + ".py"), "rb").read())
    return h.hexdigest()[:12]
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
    p.add_argument("--step", type=int, default=1, help="une image sur N (aperçu rapide)")
    p.add_argument("--samples", type=int, default=None)
    p.add_argument("--plate-samples", type=int, default=None)
    p.add_argument("--scale", type=float, default=None, help="pixels par unité de maquette (défaut : 1.5 vue générale, 1.25 vues rapprochées)")
    p.add_argument("--out", default=None)
    p.add_argument("--no-cars", action="store_true")
    p.add_argument("--save-blend", action="store_true")
    p.add_argument("--blend", action="store_true", help="construire la scène et l'enregistrer dans blender/scenes/ (sans rendu)")
    p.add_argument("--full", action="store_true", help="avec --anim : images complètes (contrôle), sans zones")
    p.add_argument("--redo-plate", action="store_true")
    p.add_argument("--chunk", type=int, default=240, help="avec --anim : images rendues par processus Blender (0 = un seul processus)")
    return p.parse_args(argv)


# ------------------------------------------------------------------ zones d'influence
def _project(scene, cam, pts):
    rx, ry = scene.render.resolution_x, scene.render.resolution_y
    out = []
    for p in pts:
        co = world_to_camera_view(scene, cam, Vector(p))
        out.append((co.x * rx, co.y * ry))
    return out


def _car_points(chain, k, f, night):
    """Points du monde qui englobent tout ce qu'un véhicule modifie à l'image f :
    carrosserie (avec flou de mouvement), ombre portée, faisceaux des phares la nuit.
    Liste vide quand il est hors trajet (retiré de la scène)."""
    pts = []
    sun = -stage.KEY_FROM
    d, trip = chain.d, chain.trip
    for df in (-1.0, 0.0, 1.0):
        tau = float(chain.tau((f + df) / C.FPS, k))
        if tau > trip.T:
            continue
        st = trip.sample(tau)
        x, y, z = float(st["x"]), float(st["y"]), float(st["z"])
        z0 = min(z, float(st["zf"])) - 0.25
        z1 = max(z, float(st["zf"])) + d.height + 0.25
        cs = R.corners(st, d, margin=0.45)
        for cx, cy in cs:
            pts.append((cx, cy, z0))
            pts.append((cx, cy, z1))
            # ombre du toit sur le sol du véhicule
            s = (z1 - z0) / -sun.z
            pts.append((cx + sun.x * s, cy + sun.y * s, z0))
        indoors = -C.BX < x < C.BX and -C.BY < y < C.BY
        if not night:
            on_roof = z > C.ROOF_Z - 0.2 and -C.BX < x < C.BX - 3.5 and -C.BY < y < C.BY - 3.5
            covered = indoors and z < C.ROOF_Z - 0.2
            if z > 0.6 and not on_roof and not covered:  # rampe, passerelles : l'ombre peut tomber jusqu'au sol
                s = z1 / -sun.z
                for cx, cy in cs:
                    pts.append((cx + sun.x * s, cy + sun.y * s, 0.0))
        else:
            c, s_ = math.cos(float(st["psi"])), math.sin(float(st["psi"]))
            # ombres portées par les lampadaires proches (elles s'allongent à l'opposé de la lampe)
            zt = z0 + d.height + 0.45
            for lx, ly, lz in world.LAMP_HEADS:
                if lz < zt + 1.0 or lz > zt + 8.0 or math.hypot(lx - x, ly - y) > 9.5:
                    continue
                grow = (lz - z0) / (lz - zt)
                for cx, cy in R.corners(st, d, margin=0.3):
                    sx, sy = lx + (cx - lx) * grow, ly + (cy - ly) * grow
                    dd = math.hypot(sx - cx, sy - cy)
                    if dd > 4.0:
                        sx, sy = cx + (sx - cx) * 4.0 / dd, cy + (sy - cy) * 4.0 / dd
                    pts.append((sx, sy, z0))
            reach = actors.BEAM_REACH + 0.3
            lit = float(actors.lights_on(trip, tau - 1 / C.FPS)) + float(actors.lights_on(trip, tau + 1 / C.FPS)) > 1e-3
            # cône des phares : demi-angle 25°, éclairage nul au-delà de BEAM_REACH
            for dist in (d.nose, reach * 0.5, reach) if lit else ():
                half = 0.9 + 0.5 * dist
                for side in (-1, 1):
                    px, py = x + dist * c - side * half * s_, y + dist * s_ + side * half * c
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


def _merge(rects, budget):
    """Regroupe les zones quand l'union coûte à peine plus de pixels que les deux séparées
    (chaque rendu a un coût fixe d'environ 0,3 s, soit budget pixels). Deux zones qui se
    chevauchent un peu restent séparées : la partie commune est simplement rendue deux fois."""
    rects = [list(r) for r in rects]

    def area(r):
        return (r[2] - r[0]) * (r[3] - r[1])

    def union(a, b):
        return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]

    while len(rects) > 1:
        best = None
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                u = union(rects[i], rects[j])
                extra = area(u) - area(rects[i]) - area(rects[j])
                if best is None or extra < best[0]:
                    best = (extra, i, j, u)
        extra, i, j, u = best
        if extra > budget:
            break
        rects = [r for k, r in enumerate(rects) if k not in (i, j)] + [u]
    return rects


def frame_zones(scene, cam, info, f, night):
    """Zones à rendre pour l'image f : [(x0, y0, x1, y1, empreinte)] en pixels, origine en bas à
    gauche. L'empreinte décrit l'état de tout ce qui est animé dans la zone (aux images f - 1,
    f et f + 1, pour le flou) : deux zones de même empreinte ont exactement la même image."""
    fleet, sigs = info["fleet"], info["sigs"]
    dg = bpy.context.evaluated_depsgraph_get()
    items = []
    for item in info["registry"]:
        if item["kind"] == "car":
            name = item["root"]
            pts = _car_points(fleet.chains[item["chain"]], item["k"], f, night)
        else:
            name = item["name"]
            if not any(a <= f <= b for a, b in item["active"]):
                continue
            if item["kind"] == "box":
                lo, hi = item["min"], item["max"]
                pts = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
            else:
                pts = _obj_points(bpy.data.objects[name], item.get("pad", 0.5), dg, night, item.get("children", False))
        r = _rect(scene, cam, pts) if pts else None
        if r:
            items.append((r, name))
    scale = scene.render.resolution_x / C.FRAME_W
    out = []
    for r in _merge([it[0] for it in items], (28000 if night else 60000) * scale * scale):
        inside = sorted((name, int(sigs[name][f]), int(sigs[name][f + 1]), int(sigs[name][f + 2])) for q, name in items if q[0] < r[2] and r[0] < q[2] and q[1] < r[3] and r[1] < q[3])
        out.append(r + [hashlib.sha1(repr((r, inside)).encode()).hexdigest()[:16]])
    return out


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
    manifest = {"key": scene_key(), "samples": a.samples, "width": scene.render.resolution_x, "height": scene.render.resolution_y, "fps": C.FPS, "frames": C.FRAMES, "night": night, "feather": FEATHER, "zones": {}}
    if os.path.exists(manifest_path) and not a.redo_plate:
        old = json.load(open(manifest_path))
        if all(old.get(k) == manifest[k] for k in ("key", "samples", "width", "night", "frames")):
            manifest["zones"] = old.get("zones", {})
        else:  # autre scène ou autres réglages : tout est à refaire
            a.redo_plate = True
            print("RENDU précédent ignoré (scène ou réglages différents)", flush=True)

    # 1. fond : image de repos (hors boucle), sans les véhicules en circulation ni la cabine
    plate = os.path.join(out, "plate.png")
    if a.redo_plate or not os.path.exists(plate):
        t0 = time.time()
        hide_dynamic(info, True)
        scene.frame_set(actors.PLATE_FRAME)
        scene.render.use_motion_blur = False
        scene.cycles.samples = a.plate_samples or (1400 if night else 700)
        scene.cycles.adaptive_threshold = 0.004
        set_border(scene, None)
        scene.render.filepath = plate
        bpy.ops.render.render(write_still=True)
        hide_dynamic(info, False)
        print(f"FOND rendu en {time.time() - t0:.1f} s", flush=True)

    # 2. zones animées (une zone déjà rendue avec le même contenu est réutilisée)
    close = a.view != "hero"
    scene.cycles.samples = a.samples or ((72 if night else 64) if close else (112 if night else 80))
    scene.cycles.adaptive_threshold = 0.012
    scene.render.use_motion_blur = True
    fa, fb = (int(v) for v in a.frames.split("-")) if a.frames else (0, C.FRAMES - 1)
    step = a.step
    t0 = time.time()
    done = made = px = 0
    for f in range(fa, fb + 1, step):
        scene.frame_set(f)
        zones = frame_zones(scene, cam, info, f, night)
        for x0, y0, x1, y1, sig in zones:
            path = os.path.join(out, "zones", f"{sig}.png")
            if os.path.exists(path) and not a.redo_plate:
                continue
            set_border(scene, [x0, y0, x1, y1])
            scene.render.filepath = path
            bpy.ops.render.render(write_still=True)
            px += (x1 - x0) * (y1 - y0)
            made += 1
        manifest["zones"][str(f)] = zones
        done += 1
        if done % 20 == 0 or f + step > fb:
            json.dump(manifest, open(manifest_path, "w"))
            el = time.time() - t0
            total = scene.render.resolution_x * scene.render.resolution_y
            print(f"IMAGE {f} : {done} images, {made} zones rendues, {el / done:.2f} s/image, {100 * px / done / total:.1f} % du cadre, reste ~{el / done * (fb - f) / step / 60:.1f} min", flush=True)
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


def _chunk_done(a, out, s, e):
    """Morceau déjà rendu (reprise après interruption) : toutes ses images sont dans le
    manifeste de la même scène et toutes leurs zones existent."""
    path = os.path.join(out, "manifest.json")
    if not os.path.exists(path):
        return False
    try:
        man = json.load(open(path))
    except ValueError:
        return False
    if man.get("key") != scene_key() or man.get("night") != a.night or man.get("frames") != C.FRAMES:
        return False
    zones = man.get("zones", {})
    for f in range(s, e + 1, a.step):
        if str(f) not in zones:
            return False
        if not all(os.path.exists(os.path.join(out, "zones", f"{z[4]}.png")) for z in zones[str(f)]):
            return False
    return True


def render_chunks(a):
    """Rend la boucle par morceaux, chacun dans un processus Blender neuf.
    Dans un seul processus, les données que Cycles garde d'une image à l'autre (données
    persistantes) finissent par se dérégler : après environ 1 000 images enchaînées, des
    faisceaux de phares sortaient en cônes noirs, sans la voiture. Un rendu neuf de la même
    image est propre ; repartir d'un processus neuf toutes les 240 images l'évite."""
    import subprocess

    name = f"{a.view}_{'night' if a.night else 'day'}"
    out = os.path.abspath(a.out or os.path.join(RENDERS, name))
    fa, fb = (int(v) for v in a.frames.split("-")) if a.frames else (0, C.FRAMES - 1)
    keep, skip = [], False
    for x in sys.argv[sys.argv.index("--") + 1 :]:  # mêmes réglages, sans --frames ni --chunk
        if skip:
            skip = False
        elif x in ("--frames", "--chunk"):
            skip = True
        elif not x.startswith(("--frames=", "--chunk=")):
            keep.append(x)
    chunks = [(s, min(s + a.chunk - 1, fb)) for s in range(fa, fb + 1, a.chunk)]
    t0, made = time.time(), 0
    for n, (s, e) in enumerate(chunks):
        if _chunk_done(a, out, s, e):
            print(f"MORCEAU {s}-{e} déjà rendu", flush=True)
            continue
        t1 = time.time()
        cmd = [bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", "-P", os.path.abspath(__file__), "--"]
        r = subprocess.run(cmd + keep + ["--frames", f"{s}-{e}", "--chunk", "0"])
        if r.returncode != 0:
            print(f"MORCEAU {s}-{e} : échec (code {r.returncode}) Error", flush=True)
            sys.exit(1)
        made += 1
        left = sum(1 for s2, e2 in chunks[n + 1 :])
        print(f"MORCEAU {s}-{e} terminé en {(time.time() - t1) / 60:.1f} min ; reste ~{(time.time() - t0) / made * left / 60:.0f} min", flush=True)
    print(f"ZONES terminées : {len(chunks)} morceaux en {(time.time() - t0) / 60:.1f} min", flush=True)


def main():
    a = parse_args()
    if a.scale is None:
        a.scale = 1.5 if a.view == "hero" else 1.25
    if a.anim and not a.full and a.chunk > 0 and not a.blend and not a.still:
        return render_chunks(a)
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
    out = os.path.abspath(a.out or os.path.join(RENDERS, name))
    os.makedirs(out, exist_ok=True)
    if a.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, f"{name}.blend"))
    if a.anim and a.full:
        render_full(scene, info, a, out)
    elif a.anim:
        render_anim(scene, info, a, out)


if __name__ == "__main__":
    main()
