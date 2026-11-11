"""
Plans 3D des niveaux pour l'explorateur du site.

Pour chaque niveau et chaque éclairage, trois rendus avec une caméra orthographique
(vue plongeante depuis le sud, sans occlusion entre voitures) :
  - niveau vide                        -> public/img/levels/P{n}_{thème}.webp
  - niveau plein (60 voitures)         -> une vignette par voiture, rangées dans
                                          public/img/levels/P{n}_{thème}_cars.webp
  - masque : une couleur par voiture   -> sert à découper les vignettes
et public/img/levels/levels.json : contour de chaque place et position de sa vignette.
Le site recompose l'image selon l'état en direct du parking (canvas).

  blender -b --factory-startup -P blender/levels.py            (rendu sur le processeur)
  blender -b --factory-startup -P blender/levels.py -- --gpu --levels 3
"""

import argparse
import json
import math
import os
import subprocess
import sys
import time

import bpy
import numpy as np
import OpenImageIO as oiio
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import actors  # noqa: E402
import cars as cars_lib  # noqa: E402
import config as C  # noqa: E402
import geo  # noqa: E402
import layout  # noqa: E402
import stage  # noqa: E402
import world  # noqa: E402
from geo import Geo, rrect  # noqa: E402
from mats import Mats, hex_lin  # noqa: E402

# voitures vues de loin : un niveau de subdivision en moins (4 fois moins de triangles, moins de mémoire)
_subsurf = cars_lib._apply_subsurf
cars_lib._apply_subsurf = lambda ob, levels=3: _subsurf(ob, 2)

OUT = os.path.join(os.path.dirname(HERE), "public", "img", "levels")
TMP = os.path.join(HERE, "work", "levels")
W, H = 1600, 900
ELEV = 52.0
SPAN = 58.5  # largeur visible (m)


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--levels", default="0,1,2,3")
    p.add_argument("--samples", type=int, default=160)
    p.add_argument("--gpu", action="store_true")
    p.add_argument("--themes", default="day,night")
    return p.parse_args(argv)


# ------------------------------------------------------------------ scène d'un niveau
def build_level(level, night, spots):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    M = Mats(night)
    deco = geo.collection("niveau")
    roof = level == C.NLEV - 1

    g = Geo()  # dalle
    g.prism(rrect(-C.BX - 0.7, C.BX + 0.7, -C.BY - 0.7, C.BY + 0.7, 0.9, 6), -0.55, 0.0)
    g.to_object("dalle", deco, M["concrete"], bevel=0.08, segments=3)
    g = Geo()
    g.box(-C.BX, C.BX, -C.BY, C.BY, 0.0, 0.03)
    g.to_object("revetement", deco, M["deck"], smooth=False)

    g = Geo()  # murets et amorces de poteaux (niveau « ouvert » pour voir toutes les places)
    g.box(-C.BX - 0.45, C.BX + 0.45, C.BY + 0.05, C.BY + 0.45, 0.0, 1.0 if roof else 0.7)
    g.box(-C.BX - 0.45, -C.BX - 0.05, -C.BY - 0.45, C.BY + 0.05, 0.0, 1.0 if roof else 0.7)
    g.box(-C.BX - 0.05, C.BX + 0.45, -C.BY - 0.45, -C.BY - 0.12, 0.0, 0.24)
    g.box(C.BX + 0.12, C.BX + 0.45, -C.BY - 0.12, C.BY + 0.05, 0.0, 0.24)
    if not roof:
        for x in world.COLS_X:
            for y in world.COLS_Y:
                g.box(x - 0.25, x + 0.25, y - 0.25, y + 0.25, 0.0, 0.42)
    g.to_object("murets", deco, M["wall"], bevel=0.05, segments=2)

    # marquages : flèches, axes des allées, repère du niveau
    z = 0.042
    g = Geo()
    for ya, yb in (C.AISLE1, C.AISLE2):
        yc = (ya + yb) / 2
        x = -C.BX + C.END_AISLE + 1.0
        while x < C.BX - C.END_AISLE - 2.0:
            g.flat([(x, yc - 0.06), (x + 1.8, yc - 0.06), (x + 1.8, yc + 0.06), (x, yc + 0.06)], z, 1)
            x += 4.05
        for col in (2, 7, 12):
            world._arrow(g, C.spot_x(col), yc + 1.5, 180.0, z)
            world._arrow(g, C.spot_x(col), yc - 1.5, 0.0, z)
    for xc, hd in ((C.BX - 2.2, 90.0), (C.BX - 4.7, 270.0), (-C.BX + 2.2, 270.0), (-C.BX + 4.7, 90.0)):
        world._arrow(g, xc, 0.0, hd, z)
    g.to_object("marquage", deco, [M["mark"], M["mark_dim"]], smooth=False)
    t = geo.text("repere", f"P{level}", 3.2, deco, M["mark"], font=world._font(world.FONT_SIGN))
    geo.place(t, (C.BX - 3.1, 12.7, z + 0.004), (0, 0, 0))

    here = [s for s in spots if s["level"] == level]
    pads = {}
    for s in here:  # tapis des places spéciales
        if s["type"] == "std":
            continue
        p = pads.setdefault(s["type"], Geo())
        x0, x1, y0, y1 = world.bay_rect(s["row"], s["col"])
        p.flat(rrect(x0 + 0.5, x1 - 0.5, y0 + 0.5, y1 - 0.5, 0.3, 4), z - 0.004)
    for key, p in pads.items():
        p.to_object(f"tapis_{key}", deco, M[f"pad_{key}"], smooth=False)
    if level == 0:
        world.ev_chargers(M, deco, here)

    # voitures : une par place (objets réels, pour pouvoir les colorer une à une dans le masque)
    garage = actors.Garage(M, night)
    cars_coll = geo.collection("voitures")
    cars = []
    import random

    rng = random.Random(5)
    offsets = {s["id"]: (rng.uniform(-0.13, 0.13), rng.uniform(-0.22, 0.18), rng.uniform(-2.2, 2.2)) for s in spots}
    for s in here:
        dx, dy, da = offsets[s["id"]]
        root = geo.empty(f"voiture_{s['id']}", cars_coll)
        root.location = (s["x"] + dx, s["y"] + dy, 0.03)
        root.rotation_euler = (0, 0, math.radians(s["heading"] + 90.0 + da))
        root.scale = (C.CAR_SCALE,) * 3
        paint = M["paint_hero"] if s["hero"] else M[f"paint_{s['paint']}"]
        garage._parts(s["style"], cars_coll, {garage.base_paint: paint}, parent=root)
        garage._wheels(s["style"], cars_coll, parent=root)
        garage._plates(s["style"], cars_coll, parent=root)
        cars.append((s, root))

    # caméra orthographique, depuis le sud
    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = SPAN
    cam_data.clip_start = 1.0
    cam_data.clip_end = 500.0
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    el = math.radians(ELEV)
    pos = Vector((0.0, -150.0 * math.cos(el), 150.0 * math.sin(el) + 0.4))
    fwd = (Vector((0.0, 0.6, 0.3)) - pos).normalized()
    right = fwd.cross(Vector((0, 0, 1))).normalized()
    up = right.cross(fwd)
    m = Matrix((right, up, -fwd)).transposed().to_4x4()
    m.translation = pos
    cam.matrix_world = m
    scene.camera = cam

    # lumière : la même que dans les vidéos le jour ; plafonnier doux la nuit
    if night:
        stage._world(scene, hex_lin("#1d2f58"), 0.35)
        light = bpy.data.lights.new("plafond", "AREA")
        light.shape = "RECTANGLE"
        light.size = 64
        light.size_y = 40
        light.energy = 6500
        light.color = (1.0, 0.9, 0.78) if roof else (0.86, 0.92, 1.0)
        lo = bpy.data.objects.new("plafond", light)
        scene.collection.objects.link(lo)
        lo.location = (0, -2, 16)
    else:
        stage._world(scene, hex_lin("#e6eefb"), 0.58)
        stage._sun(scene, 3.4, 6.5, (1.0, 0.955, 0.9))
    return scene, M, deco, cars, cam


def setup_render(scene, samples, gpu, night):
    scene.render.engine = "CYCLES"
    cy = scene.cycles
    if gpu:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "OPTIX"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = d.type == "OPTIX"
        cy.device = "GPU"
        cy.denoiser = "OPTIX"
    else:
        cy.device = "CPU"
        cy.denoiser = "OPENIMAGEDENOISE"
    cy.samples = samples
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.01
    cy.use_denoising = True
    cy.max_bounces = 5
    cy.diffuse_bounces = 3
    cy.glossy_bounces = 3
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = W, H, 100
    r.film_transparent = True
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA"
    r.image_settings.color_depth = "8"
    vs = scene.view_settings
    vs.view_transform = "Standard"
    vs.look = "None"
    vs.exposure = 0.4 if night else -0.08
    vs.gamma = 1.0


def render(scene, path):
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def read(path):
    buf = oiio.ImageBuf(path)
    s = buf.spec()
    return np.asarray(buf.get_pixels(oiio.UINT8), dtype=np.uint8).reshape(s.height, s.width, s.nchannels)


def write(path, arr):
    h, w, c = arr.shape
    buf = oiio.ImageBuf(oiio.ImageSpec(w, h, c, oiio.UINT8))
    buf.set_pixels(oiio.ROI(0, w, 0, h), arr)
    buf.write(path)


def webp(src, dst, q=90):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-c:v", "libwebp", "-q:v", str(q), "-compression_level", "6", dst], check=True)


def box_blur(a, r):
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r + 1, r)
        c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float32)
        n = a.shape[axis]
        a = (np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis) - np.take(c, np.arange(0, n), axis=axis)) / (2 * r + 1)
    return a


def id_pass(scene, deco, cars, path):
    """Masque : chaque voiture d'une couleur unie (rouge = 4 x numéro), sans lissage."""
    # un seul matériau pour toutes les voitures (la géométrie reste partagée) : la couleur
    # vient de la propriété « couleur de l'objet »
    mat = bpy.data.materials.new("masque")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    info = nt.nodes.new("ShaderNodeObjectInfo")
    nt.links.new(info.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    saved = []
    for i, (_s, root) in enumerate(cars):
        for o in root.children_recursive:
            o.color = ((i + 1) * 4 / 255.0, 0.0, 1.0, 1.0)
            for slot in o.material_slots:
                saved.append((slot, slot.link, slot.material))
                slot.link = "OBJECT"
                slot.material = mat
    deco.hide_render = True
    cy, vs = scene.cycles, scene.view_settings
    keep = (cy.samples, cy.use_adaptive_sampling, cy.use_denoising, cy.filter_width, vs.view_transform, vs.exposure, cy.device)
    cy.samples, cy.use_adaptive_sampling, cy.use_denoising, cy.filter_width = 1, False, False, 0.01
    cy.device = "CPU"
    vs.view_transform, vs.exposure = "Raw", 0.0
    lights = [o for o in scene.objects if o.type == "LIGHT"]
    for o in lights:
        o.hide_render = True
    render(scene, path)
    for o in lights:
        o.hide_render = False
    cy.samples, cy.use_adaptive_sampling, cy.use_denoising, cy.filter_width, vs.view_transform, vs.exposure, cy.device = keep
    deco.hide_render = False
    for slot, link, mat in saved:
        slot.link = link
        slot.material = mat


def project(scene, cam, p):
    co = world_to_camera_view(scene, cam, Vector(p))
    return [round(co.x * W, 1), round((1 - co.y) * H, 1)]


def main():
    a = parse_args()
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(TMP, exist_ok=True)
    spots = layout.make()
    meta_path = os.path.join(OUT, "levels.json")
    meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {"width": W, "height": H, "levels": [None] * C.NLEV}
    t0 = time.time()
    for level in (int(v) for v in a.levels.split(",")):
        packing = None
        for theme in a.themes.split(","):
            night = theme == "night"
            scene, M, deco, cars, cam = build_level(level, night, spots)
            setup_render(scene, a.samples, a.gpu, night)
            name = f"P{level}_{theme}"
            cars_coll = bpy.data.collections["voitures"]
            cars_coll.hide_render = True
            render(scene, os.path.join(TMP, f"{name}_vide.png"))
            cars_coll.hide_render = False
            render(scene, os.path.join(TMP, f"{name}_plein.png"))
            if packing is None:
                id_pass(scene, deco, cars, os.path.join(TMP, f"P{level}_id.png"))
                ids = read(os.path.join(TMP, f"P{level}_id.png"))
                idx = np.where(ids[:, :, 3] > 127, np.rint(ids[:, :, 0].astype(np.float32) / 4.0).astype(np.int32), 0)
                # vignette = voiture + halo doux (ombre de contact), sans empiéter sur les voisines
                alphas, rects = [], []
                for i in range(len(cars)):
                    own = (idx == i + 1).astype(np.float32)
                    if own.sum() < 20:
                        alphas.append(None)
                        rects.append(None)
                        continue
                    halo = np.clip(box_blur(box_blur(own, 5), 4) * 3.2, 0.0, 1.0)
                    alpha = np.maximum(own, halo * 0.92)
                    alpha[(idx != 0) & (idx != i + 1)] = 0.0
                    ys, xs = np.where(alpha > 0.02)
                    rects.append((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
                    alphas.append(alpha)
                # rangement en bandes dans une planche
                order = sorted((i for i in range(len(cars)) if rects[i]), key=lambda i: -(rects[i][3] - rects[i][1]))
                aw, x, y, row_h, place = 1280, 0, 0, 0, {}
                for i in order:
                    w, h = rects[i][2] - rects[i][0], rects[i][3] - rects[i][1]
                    if x + w + 2 > aw:
                        x, y, row_h = 0, y + row_h + 2, 0
                    place[i] = (x, y)
                    x += w + 2
                    row_h = max(row_h, h)
                packing = {"alphas": alphas, "rects": rects, "place": place, "size": (aw, y + row_h)}
                # géométrie des places (pixels de l'image) ; dessin de l'arrière vers l'avant
                entries = []
                for i, (s, _root) in enumerate(cars):
                    x0, x1, y0, y1 = world.bay_rect(s["row"], s["col"])
                    _inner, outer = world._loop_pts(x0, x1, y0, y1)
                    e = {
                        "id": s["id"],
                        "poly": [project(scene, cam, (px, py, 0.03)) for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))],
                        "loop": [project(scene, cam, (px, py, 0.04)) for px, py in outer],
                        "y": s["y"],
                    }
                    if rects[i]:
                        r = rects[i]
                        e["sprite"] = [int(place[i][0]), int(place[i][1]), int(r[2] - r[0]), int(r[3] - r[1]), int(r[0]), int(r[1])]
                    entries.append(e)
                entries.sort(key=lambda e: -e["y"])
                for e in entries:
                    del e["y"]
                meta["levels"][level] = {"spots": entries}
            full = read(os.path.join(TMP, f"{name}_plein.png")).astype(np.float32)
            aw, ah = packing["size"]
            atlas = np.zeros((ah, aw, 4), dtype=np.uint8)
            for i, alpha in enumerate(packing["alphas"]):
                if alpha is None:
                    continue
                x0, y0, x1, y1 = packing["rects"][i]
                px, py = packing["place"][i]
                tile = full[y0:y1, x0:x1].copy()
                tile[:, :, 3] *= alpha[y0:y1, x0:x1]
                atlas[py : py + (y1 - y0), px : px + (x1 - x0)] = np.clip(tile, 0, 255).astype(np.uint8)
            write(os.path.join(TMP, f"{name}_cars.png"), atlas)
            webp(os.path.join(TMP, f"{name}_cars.png"), os.path.join(OUT, f"{name}_cars.webp"))
            webp(os.path.join(TMP, f"{name}_vide.png"), os.path.join(OUT, f"{name}.webp"))
            print(f"NIVEAU {name} : planche {aw} x {ah}, {len(packing['place'])} voitures ({time.time() - t0:.0f} s)", flush=True)
        json.dump(meta, open(meta_path, "w"), separators=(",", ":"))
    print(f"TERMINE en {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
