"""
Assemble une vidéo AutoPark 3D : fond fixe + zones animées -> images -> MP4 H.264.

  blender -b --factory-startup -P blender/compose.py -- --name hero_day
  blender -b --factory-startup -P blender/compose.py -- --name hero_night --frames 0-59 --png dossier

(lancé avec le Python de Blender : numpy et OpenImageIO y sont fournis)
"""

import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np
import OpenImageIO as oiio

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402

WORK = os.path.join(HERE, "work")
PUBLIC = os.path.join(os.path.dirname(HERE), "public", "video")


def hex_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)], dtype=np.float32)


def read(path):
    buf = oiio.ImageBuf(path)
    spec = buf.spec()
    px = buf.get_pixels(oiio.FLOAT)
    return np.asarray(px, dtype=np.float32).reshape(spec.height, spec.width, spec.nchannels)


def premult(img):
    """RGBA à alpha droit -> prémultiplié ; RGB -> RGBA opaque."""
    if img.shape[2] == 3:
        return np.concatenate([img, np.ones_like(img[:, :, :1])], axis=2)
    out = img.copy()
    out[:, :, :3] *= out[:, :, 3:4]
    return out


def feather_mask(h, w, f, edges):
    """Masque 0 -> 1 sur f pixels depuis les bords (sauf ceux collés au bord du cadre)."""

    def ramp(n, lo, hi):
        r = np.ones(n, dtype=np.float32)
        t = (np.arange(f, dtype=np.float32) + 0.5) / f
        t = t * t * (3 - 2 * t)
        k = min(f, n // 2)
        if lo:
            r[:k] = t[:k]
        if hi:
            r[n - k :] = np.minimum(r[n - k :], t[:k][::-1])
        return r

    my = ramp(h, edges[0], edges[1])
    mx = ramp(w, edges[2], edges[3])
    return my[:, None] * mx[None, :]


def box_blur(a, r):
    """Flou boîte séparable (sommes cumulées), bords répétés."""
    if r < 1:
        return a
    for axis in (0, 1):
        pad = [(0, 0)] * a.ndim
        pad[axis] = (r + 1, r)
        p = np.pad(a, pad, mode="edge")
        c = np.cumsum(p, axis=axis, dtype=np.float32)
        n = a.shape[axis]
        hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
        lo = np.take(c, np.arange(0, n), axis=axis)
        a = (hi - lo) / (2 * r + 1)
    return a


def bloom(rgb, strength=0.55):
    """Halo doux autour des lumières (mode nuit) : seuil, flous larges, addition."""
    h, w, _ = rgb.shape
    out = rgb
    lum = rgb.max(axis=2, keepdims=True)
    bright = rgb * np.clip((lum - 0.62) / 0.38, 0.0, 1.0) ** 1.5
    for k, radius, gain in ((4, 3, 0.55), (8, 5, 0.4), (16, 6, 0.3)):
        hh, ww = h // k, w // k
        small = bright[: hh * k, : ww * k].reshape(hh, k, ww, k, 3).mean(axis=(1, 3))
        for _ in range(3):
            small = box_blur(small, radius)
        up = np.repeat(np.repeat(small, k, axis=0), k, axis=1)
        up = box_blur(up, k // 2)
        full = np.zeros_like(rgb)
        full[: hh * k, : ww * k] = up
        out = out + full * gain * strength
    return out


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--frames", default=None)
    p.add_argument("--png", default=None, help="écrire des PNG dans ce dossier au lieu de la vidéo")
    p.add_argument("--crf", type=int, default=19)
    p.add_argument("--no-bloom", action="store_true")
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)

    folder = a.name if os.path.isabs(a.name) else os.path.join(WORK, "render", a.name)
    man = json.load(open(os.path.join(folder, "manifest.json")))
    W, H, night, fe = man["width"], man["height"], man["night"], man["feather"]
    page = hex_rgb(C.PAGE_NIGHT if night else C.PAGE_DAY)
    plate = premult(read(os.path.join(folder, "plate.png")))
    assert plate.shape[:2] == (H, W), plate.shape
    fa, fb = (int(v) for v in a.frames.split("-")) if a.frames else (0, man["frames"] - 1)
    rng = np.random.default_rng(1)

    proc = None
    if a.png:
        os.makedirs(a.png, exist_ok=True)
    else:
        os.makedirs(PUBLIC, exist_ok=True)
        dst = a.out or os.path.join(PUBLIC, f"{a.name}.mp4")
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(man["fps"]), "-i", "-"]
        cmd += ["-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"]
        cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", str(a.crf), "-profile:v", "high", "-g", str(man["fps"]), "-bf", "2"]
        cmd += ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", "-movflags", "+faststart", "-an", dst]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    t0 = time.time()
    for f in range(fa, fb + 1):
        img = plate.copy()
        for i, (x0, y0, x1, y1) in enumerate(man["zones"].get(str(f), [])):
            z = premult(read(os.path.join(folder, "zones", f"{f:04d}_{i}.png")))
            h, w = y1 - y0, x1 - x0
            assert z.shape[:2] == (h, w), (f, i, z.shape, (h, w))
            # (y0, y1 comptés depuis le bas du cadre)
            top, bot = H - y1, H - y0
            m = feather_mask(h, w, fe, (top > 0, bot < H, x0 > 0, x1 < W))[:, :, None]
            img[top:bot, x0:x1] = img[top:bot, x0:x1] * (1 - m) + z * m
        rgb = img[:, :, :3] + page[None, None, :] * (1 - img[:, :, 3:4])
        if night and not a.no_bloom:
            rgb = bloom(rgb)
        rgb = np.clip(rgb * 255.0 + rng.uniform(-0.5, 0.5, size=(H, W, 1)).astype(np.float32) + 0.5, 0, 255).astype(np.uint8)
        if a.png:
            out = oiio.ImageBuf(oiio.ImageSpec(W, H, 3, oiio.UINT8))
            out.set_pixels(oiio.ROI(0, W, 0, H), rgb)
            out.write(os.path.join(a.png, f"{f:04d}.png"))
        else:
            proc.stdin.write(rgb.tobytes())
        if (f - fa) % 60 == 59:
            print(f"ASSEMBLAGE image {f} ({(time.time() - t0) / (f - fa + 1):.2f} s/image)", flush=True)
    if proc:
        proc.stdin.close()
        proc.wait()
        print("VIDEO", dst, os.path.getsize(dst), "octets", flush=True)
        # image fixe (affichée si la lecture automatique est bloquée)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", dst, "-frames:v", "1", "-q:v", "3", dst[:-4] + ".jpg"])
    print(f"TERMINE en {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
