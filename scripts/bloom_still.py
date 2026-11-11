"""Applique le halo du mode nuit (compose.bloom) à une image fixe : mise au point du look."""
import os, sys
import numpy as np
import OpenImageIO as oiio
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender"))
import compose

src, dst = sys.argv[1], sys.argv[2]
strength = float(sys.argv[3]) if len(sys.argv) > 3 else 0.55
img = compose.read(src)[:, :, :3]
out = np.clip(compose.bloom(img, strength) * 255 + 0.5, 0, 255).astype(np.uint8)
h, w, _ = out.shape
buf = oiio.ImageBuf(oiio.ImageSpec(w, h, 3, oiio.UINT8))
buf.set_pixels(oiio.ROI(0, w, 0, h), out)
buf.write(dst)
