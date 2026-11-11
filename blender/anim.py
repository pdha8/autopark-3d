"""Écriture rapide de courbes d'animation (une clé par image, interpolation linéaire)."""

import bpy
import numpy as np


def _channelbag(idblock):
    ad = idblock.animation_data or idblock.animation_data_create()
    if ad.action is None:
        ad.action = bpy.data.actions.new(idblock.name + "_anim")
    act = ad.action
    if not hasattr(act, "slots"):  # anciennes versions
        return act
    slot = ad.action_slot
    if slot is None:
        slot = act.slots.new(id_type=idblock.id_type, name=idblock.name)
        ad.action_slot = slot
    layer = act.layers[0] if len(act.layers) else act.layers.new("anim")
    strip = layer.strips[0] if len(layer.strips) else layer.strips.new(type="KEYFRAME")
    return strip.channelbag(slot, ensure=True)


def curve(idblock, data_path, index, frames, values):
    """Courbe complète : frames et values sont deux tableaux de même longueur."""
    bag = _channelbag(idblock)
    fc = bag.fcurves.new(data_path, index=index)
    n = len(frames)
    fc.keyframe_points.add(n)
    co = np.empty(2 * n, dtype=np.float32)
    co[0::2] = frames
    co[1::2] = values
    fc.keyframe_points.foreach_set("co", co)
    fc.keyframe_points.foreach_set("interpolation", np.full(n, 1, dtype=np.int32))  # 1 = LINEAR
    fc.update()
    return fc


def curves(idblock, data_path, frames, columns):
    """Plusieurs composantes (x, y, z…) d'une même propriété."""
    for i, col in enumerate(columns):
        if col is not None:
            curve(idblock, data_path, i, frames, col)
