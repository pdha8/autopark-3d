"""
Planche de contrôle des gabarits de véhicules (une image, rendu rapide).

  blender -b --factory-startup -P scripts/lineup.py -- [sortie.png]
"""
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender"))
import actors  # noqa: E402
import config as C  # noqa: E402
import geo  # noqa: E402
import stage  # noqa: E402
from mats import Mats  # noqa: E402

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv and len(sys.argv) > sys.argv.index("--") + 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender", "work", "stills", "lineup.png")
LINEUP = [("mini", "#2563eb"), ("hatch", 0), ("sedan", 2), ("taxi", "#f2c230"), ("coupe", "#d23a34"), ("suv", 3), ("pickup", "#e8762c"), ("van", 0)]

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
M = Mats(False)
garage = actors.Garage(M, False)
coll = geo.collection("planche")
g = geo.Geo()
g.box(-20, 20, -12, 12, -0.2, 0.0)
g.to_object("sol", coll, M["deck"], smooth=False)
for row, heading in ((0, 35.0), (1, 215.0)):  # vus de trois quarts avant, puis arrière
    for i, (style, paint) in enumerate(LINEUP):
        x = (i - (len(LINEUP) - 1) / 2) * 3.7
        ob = garage.static_car(f"{style}_{row}", style, paint, coll)
        ob.location = (x, -3.2 + row * 6.4, 0.0)
        ob.rotation_euler = (0, 0, math.radians(heading))
        ob.scale = (C.CAR_SCALE,) * 3
stage.setup_render(scene, False, 96, 1.0)
scene.render.resolution_x, scene.render.resolution_y = 2400, 1000
scene.render.film_transparent = False
spec = {"target": (0.0, 0.3, 0.8), "az": 78.0, "el": 24.0, "dist": 70.0, "lens": 85.0}
C.FRAME_W, C.FRAME_H = 2400, 1000
stage.setup_camera(scene, "planche", spec)
stage.setup_light(scene, False)
scene.render.filepath = os.path.abspath(OUT)
bpy.ops.render.render(write_still=True)
print("RENDERED", scene.render.filepath)
