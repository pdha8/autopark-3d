"""Marches dues au découpage en zones : au passage f-1 -> f, là où la couverture par les zones
change, on compare le saut f-1 -> f aux sauts voisins (f-2 -> f-1 et f -> f+1). Une marche
nette = la lumière des voitures (reflets, lumière indirecte) qui apparaît ou disparaît d'un coup.
Usage : python scripts/check_steps.py gate_night [video.mp4]
(Python de Blender ; ffmpeg dans le PATH ; les zones de la vue doivent encore exister : KEEP_ZONES=1)
"""
import json
import os
import subprocess
import sys
import time
from collections import deque

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
name = sys.argv[1]
video = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "public", "video", f"{name}.mp4")
folder = os.path.join(ROOT, "blender", "work", "render-48s", name)
for _ in range(20):
    try:
        man = json.load(open(os.path.join(folder, "manifest.json")))
        break
    except ValueError:
        time.sleep(0.5)
W, H, n = man["width"], man["height"], man["frames"]
k, B = 4, 12
w, h = W // k, H // k
bh, bw = h // B, w // B
cy = (np.arange(bh) * B + B / 2) * k
cx = (np.arange(bw) * B + B / 2) * k
covers = {}


def cover(f):
    f %= n
    if f not in covers:
        m = np.zeros((bh, bw), bool)
        for x0, y0, x1, y1, _ in man["zones"][str(f)]:
            m |= ((cy >= H - y1) & (cy < H - y0))[:, None] & ((cx >= x0) & (cx < x1))[None, :]
        covers[f] = m
    return covers[f]


def blocks(a, b):
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2).astype(np.float32)
    return d[: bh * B, : bw * B].reshape(bh, B, bw, B).mean(axis=(1, 3))


rows = []
win = deque(maxlen=4)


def step(f, fr):  # passage f-1 -> f ; fr = images f-2, f-1, f, f+1
    ch = cover(f - 1) != cover(f)
    if not ch.any():
        return
    d = blocks(fr[1], fr[2])
    base = np.maximum(blocks(fr[0], fr[1]), blocks(fr[2], fr[3]))
    s = (d - base)[ch]
    i = int(s.argmax())
    ys, xs = np.nonzero(ch)
    rows.append((float(s[i]), int(ch.sum()), f % n, int(xs[i] * B * k), int(ys[i] * B * k)))


cmd = ["ffmpeg", "-v", "error", "-i", video, "-vf", f"scale={w}:{h}:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
head = []
i = 0
while True:
    raw = p.stdout.read(w * h * 3)
    if len(raw) < w * h * 3:
        break
    c = np.frombuffer(raw, np.uint8).reshape(h, w, 3)
    if i < 3:
        head.append(c)
    win.append(c)
    if len(win) == 4:
        step(i - 1, list(win))
    i += 1
p.wait()
for j, c in enumerate(head):  # boucle : n-2 -> n-1, n-1 -> 0, 0 -> 1
    win.append(c)
    step(i - 1 + j + 1, list(win))
print(f"{name} : {i} images, {len(rows)} passages où la couverture change")
for t in (2, 4, 6, 10):
    print(f"  marche > {t:2d} : {sum(1 for r in rows if r[0] > t)} passages")
print("les plus fortes (marche, blocs changés, passage vers l'image, x, y) :")
for r in sorted(rows, reverse=True)[:30]:
    print(f"  {r[0]:6.1f}  {r[1]:4d} blocs  -> image {r[2]:4d}  vers x {r[3]}, y {r[4]}")
json.dump(sorted(rows, reverse=True), open(os.path.join(ROOT, "blender", "work", f"steps_{name}.json"), "w"))
