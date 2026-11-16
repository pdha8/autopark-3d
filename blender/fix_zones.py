"""Complète les zones d'une vue de nuit déjà rendue.

La nuit, la lumière des voitures (reflets sur le pilier brillant, lueur des feux arrière sur
les murs, lumière qui entre par les bords du cadre) touche des surfaces hors de leurs zones.
Selon le découpage de chaque image, ces surfaces viennent tantôt du rendu (avec cette
lumière), tantôt du fond fixe (sans) : la lumière apparaît ou disparaît d'un coup.
Ce script rend chaque rectangle fixe donné en zone supplémentaire, dans toutes les images où
les zones existantes ne le couvrent pas entièrement (fondu compris), et l'ajoute au manifeste.

  blender -b --factory-startup --python-exit-code 1 -P blender/fix_zones.py -- --view gate --night
      --rect 840,120,1176,640 --rect 696,0,1320,192 [--frames 0-2879] [--chunk 240] [--plan]

Rectangles en pixels de l'image finale, origine en haut à gauche : x0,y0,x1,y1. Suffixe
facultatif @a-b,c-d : le rectangle ne sert que sur ces plages d'images (lisse levée, par exemple :
le fond montre la lisse baissée, il faut alors couvrir sa position de repos).
Reprend là où il s'est arrêté ; par morceaux de 240 images, chacun dans un processus neuf.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402
import render as RD  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1 :]
p = argparse.ArgumentParser()
p.add_argument("--view", required=True)
p.add_argument("--night", action="store_true")
p.add_argument("--rect", action="append", required=True)
p.add_argument("--frames", default=None)
p.add_argument("--chunk", type=int, default=240)
p.add_argument("--samples", type=int, default=None)
p.add_argument("--plan", action="store_true", help="compter seulement, sans rendre")
a = p.parse_args(argv)
rects, RANGES = [], {}  # --rect x0,y0,x1,y1[@a-b,c-d] : seulement sur ces plages d'images
for spec in a.rect:
    box, _, when = spec.partition("@")
    r = tuple(int(v) for v in box.split(","))
    rects.append(r)
    RANGES[r] = [tuple(int(v) for v in w.split("-")) for w in when.split(",")] if when else None
name = f"{a.view}_{'night' if a.night else 'day'}"
out = os.path.join(RD.RENDERS, name)
mpath = os.path.join(out, "manifest.json")


def load():
    for _ in range(40):
        try:
            return json.load(open(mpath))
        except ValueError:
            time.sleep(0.5)
    raise RuntimeError("manifeste illisible")


def save(man):
    tmp = mpath + ".tmp"
    json.dump(man, open(tmp, "w"))
    os.replace(tmp, mpath)


def needed(man, f):
    """Rectangles pas entièrement couverts (fondu exclu) par les zones de l'image f."""
    W, H, fe = man["width"], man["height"], man["feather"]
    have = {z[4] for z in man["zones"][str(f)]}
    todo = []
    for sx0, sy0, sx1, sy1 in rects:
        when = RANGES[(sx0, sy0, sx1, sy1)]
        if when and not any(s <= f <= e for s, e in when):
            continue
        if sig(f, [sx0, H - sy1, sx1, H - sy0]) in have:  # déjà complété (reprise)
            continue
        cov = np.zeros((sy1 - sy0, sx1 - sx0), bool)
        for x0, y0, x1, y1, _ in man["zones"][str(f)]:
            t, b, l, r = H - y1, H - y0, x0, x1
            t2 = t + (fe if t > 0 else 0)  # partie à poids 1 (hors fondu)
            b2 = b - (fe if b < H else 0)
            l2 = l + (fe if l > 0 else 0)
            r2 = r - (fe if r < W else 0)
            t2, b2, l2, r2 = max(t2, sy0), min(b2, sy1), max(l2, sx0), min(r2, sx1)
            if t2 < b2 and l2 < r2:
                cov[t2 - sy0 : b2 - sy0, l2 - sx0 : r2 - sx0] = True
        if not cov.all():
            todo.append((sx0, sy0, sx1, sy1))
    return todo


def sig(f, r):
    return hashlib.sha1(repr(("fix", f, list(r))).encode()).hexdigest()[:16]


def frames():
    fa, fb = (int(v) for v in a.frames.split("-")) if a.frames else (0, C.FRAMES - 1)
    return fa, fb


def worker():
    import scene as scn

    t0 = time.time()
    scale = 1.5 if a.view == "hero" else 1.25
    scene, info = scn.build(a.night, a.view, 64, scale)
    close = a.view != "hero"
    default = (72 if a.night else 64) if close else (112 if a.night else 80)
    man = load()
    assert (a.samples or default) == (man["samples"] or default), "échantillons différents du rendu"
    assert man["night"] == a.night and man["key"] == RD.scene_key(), "autre scène que le rendu"
    scene.cycles.samples = a.samples or default  # mêmes réglages que les zones de render.py
    scene.cycles.adaptive_threshold = 0.012
    scene.render.use_motion_blur = True
    W, H = man["width"], man["height"]
    assert (W, H) == (scene.render.resolution_x, scene.render.resolution_y), "résolution différente du rendu"
    print(f"SCENE construite en {time.time() - t0:.1f} s", flush=True)
    fa, fb = frames()
    t0 = time.time()
    made = px = done = 0
    for f in range(fa, fb + 1):
        todo = needed(man, f)
        if not todo:
            continue
        scene.frame_set(f)
        for sx0, sy0, sx1, sy1 in todo:
            r = [sx0, H - sy1, sx1, H - sy0]  # origine en bas à gauche, comme le manifeste
            s = sig(f, r)
            path = os.path.join(out, "zones", f"{s}.png")
            if not os.path.exists(path):
                RD.set_border(scene, r)
                scene.render.filepath = path
                bpy.ops.render.render(write_still=True)
                made += 1
                px += (sx1 - sx0) * (sy1 - sy0)
            man["zones"][str(f)].append(r + [s])
        done += 1
        if done % 20 == 0:
            save(man)
            print(f"IMAGE {f} : {done} images complétées, {made} zones, {(time.time() - t0) / max(made, 1):.2f} s/zone", flush=True)
    save(man)
    RD.set_border(scene, None)
    print(f"COMPLETE {fa}-{fb} : {done} images, {made} zones, {px / 1e6:.1f} Mpx en {(time.time() - t0) / 60:.1f} min", flush=True)


def coordinator():
    man = load()
    fa, fb = frames()
    per = {r: [0, 0] for r in rects}
    need = {}
    for f in range(fa, fb + 1):
        todo = needed(man, f)
        if todo:
            need[f] = todo
        for r in todo:
            per[r][0] += 1
            per[r][1] += (r[2] - r[0]) * (r[3] - r[1])
    for r, (nf, px) in per.items():
        print(f"RECT {r} : {nf} images, {px / 1e6:.1f} Mpx", flush=True)
    print(f"TOTAL {len(need)} images à compléter, {sum(len(v) for v in need.values())} zones, {sum(v[1] for v in per.values()) / 1e6:.1f} Mpx", flush=True)
    if a.plan or not need:
        return
    bak = mpath + ".avant_fix"
    if not os.path.exists(bak):
        shutil.copy(mpath, bak)
    t0 = time.time()
    chunks = [(s, min(s + a.chunk - 1, fb)) for s in range(fa, fb + 1, a.chunk)]
    for s, e in chunks:
        if not any(s <= f <= e for f in need):
            continue
        t1 = time.time()
        cmd = [bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", "-P", os.path.abspath(__file__), "--", "--view", a.view, "--frames", f"{s}-{e}", "--chunk", "0"]
        cmd += ["--night"] if a.night else []
        cmd += ["--samples", str(a.samples)] if a.samples else []
        for spec in a.rect:
            cmd += ["--rect", spec]
        rc = subprocess.run(cmd).returncode
        if rc != 0:
            print(f"MORCEAU {s}-{e} : échec (code {rc}) Error", flush=True)
            sys.exit(1)
        print(f"MORCEAU {s}-{e} complété en {(time.time() - t1) / 60:.1f} min", flush=True)
    print(f"FIX terminé en {(time.time() - t0) / 60:.1f} min", flush=True)


if a.chunk > 0:
    coordinator()
else:
    worker()
