"""
Contrôle du rendu par zones : compare une image assemblée (fond + zones) à la
même image rendue en entier. Hors des zones, l'écart doit rester au niveau du
bruit ; un écart net juste à l'extérieur d'une zone = influence oubliée (ombre,
reflet, lumière) -> il faut agrandir la zone.

  python scripts/check_zones.py <dossier de rendu> <image> [dossier des PNG assemblés]
(avec le Python de Blender)
"""

import json
import os
import sys

import numpy as np
import OpenImageIO as oiio

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender"))
import config as C  # noqa: E402


def read(path):
    buf = oiio.ImageBuf(path)
    s = buf.spec()
    return np.asarray(buf.get_pixels(oiio.FLOAT), dtype=np.float32).reshape(s.height, s.width, s.nchannels)


def main():
    folder, f = sys.argv[1], int(sys.argv[2])
    test = sys.argv[3] if len(sys.argv) > 3 else os.path.join(folder, "test")
    man = json.load(open(os.path.join(folder, "manifest.json")))
    H, W = man["height"], man["width"]
    page = np.array([int((C.PAGE_NIGHT if man["night"] else C.PAGE_DAY).lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)], dtype=np.float32)
    a = read(os.path.join(test, f"{f:04d}.png"))[:, :, :3]
    b = read(os.path.join(folder, "full", f"{f:04d}.png"))
    if b.shape[2] == 4:
        b = b[:, :, :3] * b[:, :, 3:4] + page * (1 - b[:, :, 3:4])
    d = np.abs(a - b).max(axis=2) * 255
    inside = np.zeros((H, W), bool)
    core = np.zeros((H, W), bool)
    fe = man["feather"]
    for x0, y0, x1, y1 in man["zones"][str(f)]:
        inside[H - y1 : H - y0, x0:x1] = True
        core[H - y1 + fe : H - y0 - fe, x0 + fe : x1 - fe] = True
    ring = np.zeros((H, W), bool)  # couronne de 40 px juste autour des zones
    for x0, y0, x1, y1 in man["zones"][str(f)]:
        ring[max(0, H - y1 - 40) : H - y0 + 40, max(0, x0 - 40) : x1 + 40] = True
    ring &= ~core
    far = ~inside & ~ring
    for name, m in (("coeur des zones", core), ("couronne (bord + 40 px)", ring), ("reste du cadre", far)):
        v = d[m]
        print(f"{name:26s} moyenne {v.mean():5.2f}  99e centile {np.percentile(v, 99):5.2f}  max {v.max():6.1f}  (sur 255)   pixels > 12 : {(v > 12).sum()}")
    amp = np.clip(d / 255 * 10, 0, 1)
    out = oiio.ImageBuf(oiio.ImageSpec(W, H, 3, oiio.UINT8))
    rgb = np.stack([amp, amp, amp], axis=2)
    rgb[ring & (amp < 0.02), 2] = 0.25  # couronne en bleu sombre pour repérer les zones
    out.set_pixels(oiio.ROI(0, W, 0, H), (rgb * 255).astype(np.uint8))
    out.write(os.path.join(folder, f"diff_{f:04d}.png"))


if __name__ == "__main__":
    main()
