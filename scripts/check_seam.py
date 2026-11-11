"""
Contrôle du raccord de boucle sur la scène Blender construite :
  - chaque voiture k à la dernière image + 1 est exactement à la place de la voiture k+1
    à l'image 0 (position, orientation, roues, braquage) ;
  - barrières, ascenseur, couleurs des boucles, chevrons, flash : mêmes valeurs à
    l'image 0 et à l'image FRAMES.

  blender -b --factory-startup -P scripts/check_seam.py
"""
import os, sys
import bpy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender"))
import config as C
import scene as scn

scene, info = scn.build(False, "hero", 16, 0.25)


def snapshot(frame):
    scene.frame_set(frame)
    dg = bpy.context.evaluated_depsgraph_get()
    cars, misc = {}, {}
    for ob in bpy.data.collections["voitures_animees"].all_objects:
        e = ob.evaluated_get(dg)
        k = int(ob.name.split("_")[0].replace("auto", "")) if ob.name.startswith("auto") else None
        if k is None:
            root = ob
            while root.parent is not None:
                root = root.parent
            k = int(root.name.replace("auto", ""))
            key = ob.name.split(".")[0]
        else:
            key = ob.name[len(f"auto{k}"):]
        cars.setdefault(k, {}).setdefault(key, []).append([round(v, 5) for row in e.matrix_world for v in row])
    for ob in bpy.data.collections["elements_animes"].all_objects:
        e = ob.evaluated_get(dg)
        vals = [round(v, 5) for row in e.matrix_world for v in row]
        for slot in e.material_slots:
            m = slot.material
            if m and m.node_tree:
                for n in m.node_tree.nodes:
                    if n.type == "BSDF_PRINCIPLED":
                        vals += [round(v, 4) for v in n.inputs["Emission Color"].default_value]
                        vals += [round(n.inputs["Emission Strength"].default_value, 4)]
        if e.type == "LIGHT":
            vals.append(round(e.data.energy, 3))
        misc[ob.name] = vals
    return cars, misc


c0, m0 = snapshot(0)
c1, m1 = snapshot(C.FRAMES)
bad = 0
for k in range(C.N_CARS - 1):
    for key in c1[k]:
        a, b = sorted(c1[k][key]), sorted(c0[k + 1][key])
        d = max(abs(x - y) for u, v in zip(a, b) for x, y in zip(u, v))
        if d > 2e-3:
            bad += 1
            print(f"ECART voiture {k} -> {k + 1} {key} : {d:.5f}")
for name in m0:
    d = max(abs(x - y) for x, y in zip(m0[name], m1[name]))
    if d > 2e-3:
        bad += 1
        print(f"ECART {name} : {d:.5f}")
print(f"SEAM total {bad} ({sum(len(v) for v in c0.values())} pièces de voitures, {len(m0)} éléments animés)")
