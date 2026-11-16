"""Refait, dans un processus Blender neuf, les zones déjà rendues d'une plage d'images (mêmes
rectangles, mêmes noms de fichiers ; le manifeste ne change pas).

Pourquoi : le premier morceau d'un rendu (images 0-239) est rendu dans le processus qui vient de
rendre le fond à 1400 échantillons. Cycles y garde le motif d'échantillonnage du fond : les zones
de ce morceau ont un grain (et un anticrénelage des contours) un peu différent des autres
morceaux, ce qui se voit au passage 239 -> 240 et au raccord de boucle.

  blender -b --factory-startup --python-exit-code 1 -P blender/rerender_zones.py -- --view roof --night --frames 0-239
Les zones ajoutées par fix_zones.py (rendues dans des processus neufs) ne sont pas refaites.
Reprend là où il s'est arrêté (liste des zones refaites à côté du manifeste).
"""
import argparse
import json
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render as RD  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1 :]
p = argparse.ArgumentParser()
p.add_argument("--view", required=True)
p.add_argument("--night", action="store_true")
p.add_argument("--frames", required=True)
a = p.parse_args(argv)
name = f"{a.view}_{'night' if a.night else 'day'}"
out = os.path.join(RD.RENDERS, name)
mpath = os.path.join(out, "manifest.json")
orig = mpath + ".avant_fix" if os.path.exists(mpath + ".avant_fix") else mpath  # zones de render.py seulement
man = json.load(open(orig))
done_path = os.path.join(out, f"refait_{a.frames}.json")
done = set(json.load(open(done_path))) if os.path.exists(done_path) else set()

import scene as scn  # noqa: E402

t0 = time.time()
scene, info = scn.build(a.night, a.view, 64, 1.5 if a.view == "hero" else 1.25)
close = a.view != "hero"
default = (72 if a.night else 64) if close else (112 if a.night else 80)
assert man["samples"] is None, "rendu fait avec un nombre d'échantillons imposé"
assert man["night"] == a.night and man["key"] == RD.scene_key(), "autre scène que le rendu"
scene.cycles.samples = default  # mêmes réglages que les zones de render.py
scene.cycles.adaptive_threshold = 0.012
scene.render.use_motion_blur = True
W, H = man["width"], man["height"]
assert (W, H) == (scene.render.resolution_x, scene.render.resolution_y), "résolution différente du rendu"
print(f"SCENE construite en {time.time() - t0:.1f} s ; zones prises dans {os.path.basename(orig)}", flush=True)

fa, fb = (int(v) for v in a.frames.split("-"))
t0 = time.time()
made = 0
for i, f in enumerate(range(fa, fb + 1)):
    todo = [z for z in man["zones"][str(f)] if z[4] not in done]
    if todo:
        scene.frame_set(f)
    for x0, y0, x1, y1, sig in todo:
        path = os.path.join(out, "zones", f"{sig}.png")
        tmp = os.path.join(out, "zones", f"{sig}.neuf.png")
        RD.set_border(scene, [x0, y0, x1, y1])
        scene.render.filepath = tmp
        bpy.ops.render.render(write_still=True)
        os.replace(tmp, path)
        done.add(sig)
        made += 1
    if (i + 1) % 20 == 0 or f == fb:
        json.dump(sorted(done), open(done_path, "w"))
        print(f"IMAGE {f} : {made} zones refaites, {(time.time() - t0) / max(made, 1):.2f} s/zone", flush=True)
RD.set_border(scene, None)
print(f"FAIT {fa}-{fb} : {made} zones refaites en {(time.time() - t0) / 60:.1f} min", flush=True)
