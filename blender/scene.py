"""Assemble la scène complète (décor + voitures + animation) pour une vue et un éclairage."""

import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config as C  # noqa: E402
import geo  # noqa: E402
import layout  # noqa: E402
import stage  # noqa: E402
import world  # noqa: E402
from mats import Mats  # noqa: E402


def build(night=False, view="hero", samples=64, scale=1.5, cars=True, spec=None):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    M = Mats(night)
    spots = layout.make()
    decor = geo.collection("decor")
    skip = {(C.HERO_LEVEL, C.HERO_ROW, C.HERO_COL), (C.HERO_LEVEL, C.PASS_ROW, C.HERO_COL)} if cars else set()
    world.build_static(M, decor, spots, night, skip_loops=skip)
    stage.setup_render(scene, night, samples, scale)
    cam, v = stage.setup_camera(scene, view, spec)
    stage.setup_light(scene, night)
    info = {"M": M, "spots": spots, "view": v, "cam": cam, "decor": decor}
    if cars:
        import actors

        actors.set_beam_reach(view)
        info.update(actors.build(scene, M, spots, night))
    return scene, info
