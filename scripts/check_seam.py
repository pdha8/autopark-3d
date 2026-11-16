"""
Contrôle du raccord de boucle sur la scène Blender construite :
  - chaque véhicule k d'une chaîne, à la dernière image + 1, est exactement à la place du
    véhicule k + 1 à l'image 0 (position, orientation, roues, braquage, feux) ;
  - barrières, ascenseur, couleurs des boucles, chevrons, flash : mêmes valeurs à
    l'image 0 et à l'image FRAMES ;
  - un véhicule n'apparaît et ne disparaît que hors de vue : hors cadre, ou caché par le
    bâtiment (lancer de rayons vers chacune des trois caméras).

  blender -b --factory-startup -P scripts/check_seam.py
"""
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender"))
import config as C  # noqa: E402
import route as R  # noqa: E402
import scene as scn  # noqa: E402
from camera import View  # noqa: E402

scene, info = scn.build(False, "hero", 16, 0.25)
fleet = info["fleet"]


def values(e):
    vals = [round(v, 4) for row in e.matrix_world for v in row]
    for slot in e.material_slots:
        m = slot.material
        if m and m.node_tree:
            for n in m.node_tree.nodes:
                if n.type == "BSDF_PRINCIPLED":
                    vals += [round(v, 3) for v in n.inputs["Emission Color"].default_value]
                    vals += [round(n.inputs["Emission Strength"].default_value, 3)]
                elif n.type == "MATH":
                    vals.append(round(n.inputs[1].default_value, 4))
    if e.type == "LIGHT":
        vals.append(round(e.data.energy, 2))
    return vals


def snapshot(frame):
    scene.frame_set(frame)
    dg = bpy.context.evaluated_depsgraph_get()
    cars, misc = {}, {}
    for chain, k in fleet.cars():
        root = bpy.data.objects[f"{chain.name}_{k}"]
        parts = {}
        for ob in [root] + list(root.children_recursive):
            base = ob.name.split(".")[0]
            key = base[len(root.name) :] if base.startswith(root.name) else base
            parts.setdefault(key, []).append(values(ob.evaluated_get(dg)))
        cars[(chain.name, k)] = parts
    for ob in bpy.data.collections["elements_animes"].all_objects:
        misc[ob.name] = values(ob.evaluated_get(dg))
    return cars, misc


c0, m0 = snapshot(0)
c1, m1 = snapshot(C.FRAMES)
bad = pieces = 0
for chain in fleet.chains:
    for k in range(chain.m):
        a_parts, b_parts = c1[(chain.name, k)], c0[(chain.name, (k + 1) % chain.m)]
        for key in a_parts:
            pieces += len(a_parts[key])
            a, b = sorted(a_parts[key]), sorted(b_parts[key])
            d = max(abs(x - y) for u, v in zip(a, b) for x, y in zip(u, v))
            if d > 3e-3:
                bad += 1
                print(f"ECART {chain.name} {k} -> {(k + 1) % chain.m} {key} : {d:.5f}")
for name in m0:
    d = max(abs(x - y) for x, y in zip(m0[name], m1[name]))
    if d > 3e-3:
        bad += 1
        print(f"ECART {name} : {d:.5f}")
print(f"SEAM total {bad} ({pieces} pièces de véhicules, {len(m0)} éléments animés)")

# ---- apparitions et disparitions : hors de vue dans les trois cadres
for name in ("voitures_animees",):
    bpy.data.collections[name].hide_viewport = True  # les véhicules ne se cachent pas entre eux
scene.frame_set(0)
dg = bpy.context.evaluated_depsgraph_get()
views = {n: View(n) for n in C.VIEWS}
seen = 0
for chain in fleet.chains:
    for tau, label in ((0.0, "apparaît"), (chain.trip.T, "disparaît")):
        st = chain.trip.sample(tau)
        z = float(st["z"])
        pts = [Vector((x, y, z + h)) for x, y in R.corners(st, chain.d) for h in (0.35, chain.d.height)]
        pts.append(Vector((float(st["x"]), float(st["y"]), z + chain.d.height)))
        for vn, view in views.items():
            n_vis = 0
            for p in pts:
                u, v, _ = view.project(tuple(p))
                if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
                    continue
                to_cam = Vector(view.pos) - p
                hit, *_ = scene.ray_cast(dg, p + to_cam.normalized() * 0.05, to_cam.normalized(), distance=to_cam.length)
                n_vis += not hit
            if n_vis:
                seen += 1
                print(f"VISIBLE {chain.name} {label} dans la vue {vn} ({n_vis} points sur {len(pts)}) en ({float(st['x']):.1f}, {float(st['y']):.1f}, {z:.1f})")
print(f"HORS DE VUE : {seen} apparition(s) ou disparition(s) visibles")
