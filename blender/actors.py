"""
Voitures et éléments animés d'AutoPark 3D :
  - bibliothèque de voitures (carrosseries de cars.py, roues, plaques), instanciée
    pour les voitures garées ;
  - 7 voitures « héros » identiques qui se relaient sur la route (route.py) ;
  - lisses des barrières, flash de la caméra ANPR, cabine d'ascenseur, boucles
    lumineuses de la place réservée, chevrons de guidage.
Toutes les poses sont des fonctions du temps dans la boucle : la dernière image
rejoint exactement la première.
"""

import json
import math
import random

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

import anim
import cars
import config as C
import geo
import route as R
import world
from geo import Geo
from mats import hex_lin

Y_HIDE_IN = -88.0  # au sud : voiture qui arrive, phares compris, hors de tous les cadres
Y_HIDE_OUT = -76.0
FR = np.arange(-1, C.FRAMES + 2, dtype=float)  # images clés (une de plus de chaque côté : flou de mouvement)
TIME = FR / C.FPS


def get_route():
    return R.build(Y_HIDE_IN, Y_HIDE_OUT)


# ------------------------------------------------------------------ roue
def _lathe(bm, profile, n, mat):
    """Révolution d'un profil (x, r) autour de l'axe X."""
    rings = [[bm.verts.new((x, r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n))) for i in range(n)] for x, r in profile]
    for a, b in zip(rings, rings[1:]):
        for i in range(n):
            j = (i + 1) % n
            f = bm.faces.new((a[i], a[j], b[j], b[i]))
            f.material_index = mat
            f.smooth = True
    return rings


def wheel_mesh(M):
    """Roue en unités jouet : axe X, face extérieure vers +X."""
    r, w = 0.145, 0.115
    bm = bmesh.new()
    tire = [(-w / 2, 0.092), (-w / 2, 0.122), (-w / 2 + 0.014, 0.139), (-0.02, r), (0.02, r), (w / 2 - 0.014, 0.139), (w / 2, 0.122), (w / 2, 0.096)]
    _lathe(bm, tire, 40, 0)
    dish = [(w / 2, 0.096), (w / 2 - 0.006, 0.09), (w / 2 - 0.03, 0.08), (w / 2 - 0.034, 0.0001)]  # creux sombre
    _lathe(bm, dish, 40, 2)
    back = [(-w / 2, 0.0001), (-w / 2, 0.092)]
    _lathe(bm, back, 40, 0)
    lip = [(w / 2 - 0.004, 0.097), (w / 2 + 0.003, 0.093), (w / 2 + 0.003, 0.084), (w / 2 - 0.008, 0.08)]  # jante : rebord
    _lathe(bm, lip, 40, 1)
    hub = [(w / 2 - 0.034, 0.03), (w / 2 + 0.006, 0.028), (w / 2 + 0.01, 0.018), (w / 2 + 0.01, 0.0001)]
    _lathe(bm, hub, 20, 1)
    for k in range(5):  # cinq branches
        a = 2 * math.pi * k / 5
        m = Matrix.Rotation(a, 4, "X")
        x0, x1 = w / 2 - 0.03, w / 2 + 0.002
        co = [(x0, -0.016, 0.02), (x1, -0.012, 0.02), (x1, 0.012, 0.02), (x0, 0.016, 0.02), (x0, -0.012, 0.086), (x1, -0.009, 0.086), (x1, 0.009, 0.086), (x0, 0.012, 0.086)]
        v = [bm.verts.new(m @ Vector(p)) for p in co]
        for idx in ((0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)):
            f = bm.faces.new([v[i] for i in idx])
            f.material_index = 1
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new("roue")
    bm.to_mesh(me)
    bm.free()
    for name in ("rubber", "rim", "car_dark"):
        me.materials.append(M[name])
    try:
        me.set_sharp_from_angle(angle=math.radians(40))
    except Exception:
        pass
    return me


# ------------------------------------------------------------------ bibliothèque de voitures
class Garage:
    def __init__(self, M, night):
        self.M = M
        self.night = night
        self.masters = geo.collection("voitures_modeles", exclude=True)
        self.lib = geo.collection("voitures_bibliotheque", exclude=True)
        self.wheel = wheel_mesh(M)
        self.plate_me, self.plate_band_me, self.plate_ink_me = self._plate_meshes()
        self.font = world._font(world.FONT_DIN)
        self.styles = {}
        self.variants = {}
        self.base_paint = M.paint("paint_master", "#ffffff")
        for style in C.STYLES:
            mats = {"paint": self.base_paint, "roof": M["car_roof"], "glass": M["car_glass"], "chrome": M["chrome"], "dark": M["car_dark"], "lamp": M["lamp_off"], "tail": M["tail_off"]}
            objs, bvh = cars.build(style, mats, f"m_{style}")
            parts = [(o, o.matrix_world.copy()) for o in objs]
            for o in objs:
                geo.move_to(o, self.masters)
            plates = [cars.plate_spot(style, bvh, rear) for rear in (False, True)]
            self.styles[style] = {"parts": parts, "plates": plates, "wheels": cars.STYLES[style]["wheels"]}

    def _plate_meshes(self):
        out = []
        for name, (x0, x1, y0, y1, z0, z1) in (("plaque", (-0.118, 0.118, -0.027, 0.027, 0.0, 0.006)), ("plaque_bande", (-0.118, -0.094, -0.027, 0.027, 0.0, 0.0068)), ("plaque_encre", (-0.078, 0.104, -0.011, 0.011, 0.0, 0.0068))):
            g = Geo()
            g.box(x0, x1, y0, y1, z0, z1)
            bm = g.bm
            me = bpy.data.meshes.new(name)
            bm.to_mesh(me)
            bm.free()
            out.append(me)
        out[0].materials.append(self.M["plate"])
        out[1].materials.append(self.M["plate_blue"])
        out[2].materials.append(self.M["mark_dim"])
        return out

    def _parts(self, style, coll, swap, parent=None):
        """Copies des pièces d'un modèle (maillages partagés) avec matériaux remplacés."""
        made = []
        for o, mw in self.styles[style]["parts"]:
            d = o.copy()
            coll.objects.link(d)
            for slot in d.material_slots:
                if slot.material in swap:
                    new = swap[slot.material]
                    slot.link = "OBJECT"
                    slot.material = new
            if parent is not None:
                d.parent = parent
                d.matrix_parent_inverse = Matrix.Identity(4)
                d.matrix_basis = mw
            else:
                d.matrix_world = mw
            made.append(d)
        return made

    def _plates(self, style, coll, parent=None, text=None):
        for i, (loc, nor) in enumerate(self.styles[style]["plates"]):
            if loc is None:
                continue
            holder = bpy.data.objects.new(f"plaque_{style}_{i}", self.plate_me)
            coll.objects.link(holder)
            cars._orient(holder, loc + nor * 0.003, nor)
            mw = holder.matrix_world.copy()
            if parent is not None:
                holder.parent = parent
                holder.matrix_parent_inverse = Matrix.Identity(4)
                holder.matrix_basis = mw
            band = bpy.data.objects.new(f"plaque_bande_{style}_{i}", self.plate_band_me)
            coll.objects.link(band)
            band.parent = holder
            if text:
                t = geo.text(f"plaque_texte_{style}_{i}", text, 0.036, coll, self.M["plate_text"], font=self.font, extrude=0.0006, spacing=1.05)
                t.parent = holder
                t.location = (0.012, -0.001, 0.0066)
            else:
                ink = bpy.data.objects.new(f"plaque_encre_{style}_{i}", self.plate_ink_me)
                coll.objects.link(ink)
                ink.parent = holder

    def _wheels(self, style, coll, parent=None):
        wy, track = self.styles[style]["wheels"]
        made = {}
        for fx, sx in (("G", 1), ("D", -1)):
            for fy, sy in (("av", -1), ("ar", 1)):
                w = bpy.data.objects.new(f"roue_{fy}{fx}", self.wheel)
                coll.objects.link(w)
                w.location = (sx * track, sy * wy, 0.145)
                w.rotation_mode = "XYZ"
                w.rotation_euler = (0, 0, 0 if sx > 0 else math.pi)
                if parent is not None:
                    w.parent = parent
                made[fy + fx] = (w, sx)
        return made

    def variant(self, style, paint):
        """Collection instanciable d'une voiture garée (modèle + peinture)."""
        key = (style, paint)
        if key not in self.variants:
            coll = bpy.data.collections.new(f"v_{style}_{paint}")
            self.lib.children.link(coll)
            self._parts(style, coll, {self.base_paint: self.M[f"paint_{paint}"]})
            self._wheels(style, coll)
            self._plates(style, coll)
            self.variants[key] = coll
        return self.variants[key]

    def hero(self, coll, name):
        """Voiture animée : racine (pose sur la route) > caisse (roulis, tangage) + 4 roues."""
        M = self.M
        root = geo.empty(name, coll)
        root.rotation_mode = "YXZ"
        root.scale = (C.CAR_SCALE,) * 3
        body = geo.empty(name + "_caisse", coll, parent=root)
        body.rotation_mode = "YXZ"
        lamp = M["lamp_on"].copy()  # un matériau de phare par voiture : s'éteint quand elle est garée
        lamp.name = f"{name}_phare"
        swap = {self.base_paint: M["paint_hero"], M["lamp_off"]: lamp, M["tail_off"]: M["tail_on"]}
        self._parts("mini", coll, swap, parent=body)
        self._plates("mini", coll, parent=body, text="AB-123-CD")
        wheels = self._wheels("mini", coll, parent=root)
        lights = {"lamp": lamp, "spots": [], "beam": None}
        if self.night:
            lights["spots"], lights["beam"] = _headlights(coll, body, name)
        return root, body, wheels, lights


# ------------------------------------------------------------------ phares (nuit)
def _beam_material():
    mat = bpy.data.materials.get("faisceau")
    if mat:
        return mat
    mat = bpy.data.materials.new("faisceau")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    mix = nt.nodes.new("ShaderNodeMixShader")
    transp = nt.nodes.new("ShaderNodeBsdfTransparent")
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = hex_lin("#fff4e2")
    emit.inputs["Strength"].default_value = 1.0
    coord = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    fall = nt.nodes.new("ShaderNodeMapRange")  # 1 au phare, 0 au bout du cône (z local de 0 à -2)
    fall.inputs["From Min"].default_value = 0.0
    fall.inputs["From Max"].default_value = -2.0
    fall.inputs["To Min"].default_value = 1.0
    fall.inputs["To Max"].default_value = 0.0
    power = nt.nodes.new("ShaderNodeMath")
    power.operation = "POWER"
    power.inputs[1].default_value = 2.2
    lw = nt.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.5
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    soft = nt.nodes.new("ShaderNodeMath")
    soft.operation = "POWER"
    soft.inputs[1].default_value = 2.5
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul2 = nt.nodes.new("ShaderNodeMath")
    mul2.operation = "MULTIPLY"
    mul2.inputs[1].default_value = 0.36
    nt.links.new(coord.outputs["Object"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], fall.inputs["Value"])
    nt.links.new(fall.outputs["Result"], power.inputs[0])
    nt.links.new(lw.outputs["Facing"], inv.inputs[1])
    nt.links.new(power.outputs["Value"], mul.inputs[0])
    nt.links.new(inv.outputs["Value"], soft.inputs[0])
    nt.links.new(soft.outputs["Value"], mul.inputs[1])
    nt.links.new(mul.outputs["Value"], mul2.inputs[0])
    nt.links.new(mul2.outputs["Value"], mix.inputs["Fac"])
    nt.links.new(transp.outputs["BSDF"], mix.inputs[1])
    nt.links.new(emit.outputs["Emission"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


BEAM_REACH = 12.0  # portée de l'éclairage des phares (m) : au-delà, strictement aucun effet


def set_beam_reach(view):
    """Vues rapprochées : faisceaux plus courts (zones de rendu bien plus petites à l'écran)."""
    global BEAM_REACH
    BEAM_REACH = 12.0 if view == "hero" else 8.0


def headlights_on(ev, tau):
    """Phares allumés (1) ou éteints (0) : ils s'éteignent une fois la voiture garée."""
    tau = np.asarray(tau, dtype=float)
    return 1.0 - (_S((tau - ev["parked"] - 0.7) / 0.4) - _S((tau - ev["leave"] + 0.9) / 0.4))


def _limited_falloff(light, d0, d1):
    """La lumière s'éteint complètement entre d0 et d1 mètres (zone d'influence bornée)."""
    light.use_nodes = True
    nt = light.node_tree
    em = next(n for n in nt.nodes if n.type == "EMISSION")
    path = nt.nodes.new("ShaderNodeLightPath")
    ramp = nt.nodes.new("ShaderNodeMapRange")
    ramp.interpolation_type = "SMOOTHSTEP"
    ramp.inputs["From Min"].default_value = d0
    ramp.inputs["From Max"].default_value = d1
    ramp.inputs["To Min"].default_value = 1.0
    ramp.inputs["To Max"].default_value = 0.0
    nt.links.new(path.outputs["Ray Length"], ramp.inputs["Value"])
    nt.links.new(ramp.outputs["Result"], em.inputs["Strength"])


def _headlights(coll, body, name):
    """Renvoie (projecteurs, matériau des faisceaux) pour l'animation allumé / éteint."""
    L = cars.STYLES["mini"]["lamps"]
    beam = _beam_material().copy()
    beam.name = f"{name}_faisceau"
    spots = []
    for sx in (1, -1):
        spot = bpy.data.lights.new(f"{name}_phare{sx}", "SPOT")
        spot.energy = 520
        spot.spot_size = math.radians(50)
        spot.spot_blend = 0.85
        spot.shadow_soft_size = 0.08
        spot.color = (1.0, 0.95, 0.86)
        _limited_falloff(spot, BEAM_REACH * 0.55, BEAM_REACH)
        so = bpy.data.objects.new(spot.name, spot)
        coll.objects.link(so)
        so.parent = body
        so.location = (sx * L["x"], L["y"] - 0.075, L["z"])
        down = Vector((0, -1, -0.17)).normalized()
        so.rotation_euler = down.to_track_quat("-Z", "Z").to_euler()
        bpy.ops.mesh.primitive_cone_add(vertices=40, radius1=0.62, radius2=0.0, depth=2.0, end_fill_type="NOTHING")
        cone = bpy.context.active_object
        cone.name = f"{name}_faisceau{sx}"
        geo.move_to(cone, coll)
        for poly in cone.data.polygons:
            poly.use_smooth = True
        for v in cone.data.vertices:  # pointe au phare, ouverture vers -Z local
            v.co.z -= 1.0
        cone.data.materials.append(beam)
        cone.parent = so
        cone.location = (0, 0, 0)
        cone.rotation_euler = (math.radians(9), 0, 0)
        cone.visible_shadow = False
        spots.append(spot)
    return spots, beam


# ------------------------------------------------------------------ voitures garées
def parked(garage, coll, spots, only_levels=None):
    rng = random.Random(5)
    n = 0
    for s in spots:
        dx, dy, da = rng.uniform(-0.13, 0.13), rng.uniform(-0.22, 0.18), rng.uniform(-2.2, 2.2)
        if s["status"] != "occupied" or s["hero"]:
            continue
        if only_levels is not None and s["level"] not in only_levels:
            continue
        z = world.level_z(s["level"]) + (0.04 if s["level"] == 0 else 0.025)
        geo.instance(f"garee_{s['id']}", garage.variant(s["style"], s["paint"]), coll, (s["x"] + dx, s["y"] + dy, z), s["heading"] + 90.0 + da, C.CAR_SCALE)
        n += 1
    return n


# ------------------------------------------------------------------ animation
def _S(u):
    u = np.clip(u, 0.0, 1.0)
    return u * u * u * (u * (6 * u - 15) + 10)


def _periodic(f):
    """Somme d'une fonction du temps de route sur toutes les voitures -> fonction du temps de boucle."""
    return sum(f(TIME + k * C.LOOP) for k in range(-1, C.N_CARS + 1))


def _time_at_y(route, y, t0, t1):
    """Instant (entre t0 et t1) où l'essieu arrière passe à l'ordonnée y (y monotone sur l'intervalle)."""
    m = (route.t >= t0) & (route.t <= t1)
    t, yy = route.t[m], route.c["y"][m]
    if yy[0] > yy[-1]:
        t, yy = t[::-1], yy[::-1]
    return float(np.interp(y, yy, t))


def timeline(route):
    """Instants clés (temps de route d'une voiture) : barrières, flash, états de la place."""
    w = route.when
    ev = {}
    stop = w("stop")
    ev["flash"] = stop + 0.35
    ev["in_open"] = stop + 0.8
    ev["in_close"] = _time_at_y(route, C.GATE_IN_Y + R.TAIL + 1.0, w("gate_to_ramp"), w("up_a"))
    ev["out_open"] = _time_at_y(route, C.Y_TAN - 0.4, w("exit_slow"), w("exit_go"))  # dès la sortie de la rampe
    ev["out_close"] = _time_at_y(route, C.GATE_OUT_Y - R.TAIL - 1.0, w("exit_slow"), w("road_out"))
    ev["parked"] = w("parked")
    ev["leave"] = w("leave_a")
    ev["bay_clear"] = _time_at_y(route, -R.TAIL - 0.15, w("leave_a"), w("turn_east"))  # l'arrière quitte la place C
    ev["pass_in"] = _time_at_y(route, R.NOSE - 0.4, w("leave_a"), w("turn_east"))  # le nez entre sur la place B
    ev["pass_out"] = _time_at_y(route, -C.SPOT_D - R.TAIL + 0.3, w("leave_a"), w("turn_east", end=True))
    ev["reserved"] = ev["bay_clear"] - C.LOOP + 1.2  # la place libérée est réservée pour la voiture suivante
    ev["guide_on"] = ev["reserved"] + 0.25
    return ev


def bake_car(route, k, root, body, wheels):
    st = route.sample(TIME + k * C.LOOP)
    psi, pitch = st["psi"], st["pitch"]
    cp = np.cos(pitch)
    x = st["x"] + R.AXLE_Y * np.cos(psi) * cp
    y = st["y"] + R.AXLE_Y * np.sin(psi) * cp
    z = st["z"] + R.AXLE_Y * np.sin(pitch)
    anim.curves(root, "location", FR, [x, y, z])
    anim.curves(root, "rotation_euler", FR, [-pitch, None, psi + math.pi / 2])
    anim.curves(body, "rotation_euler", FR, [-st["dpitch"], st["droll"], None])
    spin = st["dist"] / C.WHEEL_R
    for key, (w, sx) in wheels.items():
        front = key.startswith("av")
        steer = st["steer"] if front else np.zeros_like(spin)
        if sx > 0:
            anim.curves(w, "rotation_euler", FR, [spin, None, steer if front else None])
        else:
            anim.curves(w, "rotation_euler", FR, [-spin, None, math.pi + steer if front else None])


def _arm_curve(ev, open_key, close_key):
    f = lambda t: _S((t - ev[open_key]) / 0.7) - _S((t - ev[close_key]) / 0.9)
    return math.radians(84.0) * _periodic(f)


def _cabin_curve():
    t = np.mod(TIME, C.LOOP)
    up = _S((t - 1.4) / 3.6) - _S((t - 7.6) / 3.6)
    return 0.14 + C.ROOF_Z * up


def _color_curve(ev, kind):
    """Couleur (linéaire) de la boucle lumineuse d'une place au fil de la boucle."""
    cols = {k: np.array(hex_lin(v)[:3]) for k, v in C.STATUS.items()}
    fade = 0.22
    if kind == "hero":  # rouge (occupée) -> verte (libérée) -> bleue (réservée) -> rouge
        red = _periodic(lambda t: _S((t - ev["parked"]) / fade) - _S((t - ev["bay_clear"]) / fade))
        blue = _periodic(lambda t: _S((t - ev["reserved"]) / fade) - _S((t - ev["parked"]) / fade))
    else:  # place traversée : rouge pendant le passage de la voiture
        red = _periodic(lambda t: _S((t - ev["pass_in"]) / fade) - _S((t - ev["pass_out"]) / fade))
        blue = np.zeros_like(red)
    red, blue = np.clip(red, 0, 1), np.clip(blue, 0, 1)
    green = np.clip(1 - red - blue, 0, 1)
    rgb = red[:, None] * cols["occupied"] + blue[:, None] * cols["reserved"] + green[:, None] * cols["available"]
    return rgb, red, blue


def _anim_material(M, name, color, strength):
    mat = M.glow(name, color, strength)
    b = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    return mat, b


def _active_ranges(mask):
    """Plages d'images (indices dans [0, FRAMES)) où mask est vrai."""
    out, start = [], None
    for f in range(C.FRAMES):
        on = bool(mask[f + 1])  # FR commence à -1
        if on and start is None:
            start = f
        if not on and start is not None:
            out.append([start, f - 1])
            start = None
    if start is not None:
        out.append([start, C.FRAMES - 1])
    return out


def build(scene, M, spots, night):
    route = get_route()
    ev = timeline(route)
    garage = Garage(M, night)
    parked_coll = geo.collection("voitures_garees")
    n_parked = parked(garage, parked_coll, spots)
    dyn_cars = geo.collection("voitures_animees")
    dyn_misc = geo.collection("elements_animes")
    registry = []

    # ---- voitures « héros »
    for k in range(C.N_CARS):
        root, body, wheels, lights = garage.hero(dyn_cars, f"auto{k}")
        bake_car(route, k, root, body, wheels)
        if night:  # phares éteints pendant que la voiture est garée
            on = headlights_on(ev, TIME + k * C.LOOP)
            lb = next(n for n in lights["lamp"].node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            anim.curve(lights["lamp"].node_tree, lb.inputs["Emission Strength"].path_from_id("default_value"), 0, FR, M.lamp * on)
            for spot in lights["spots"]:
                anim.curve(spot, "energy", 0, FR, 520.0 * on)
            gain = next(n for n in lights["beam"].node_tree.nodes if n.type == "MATH" and n.operation == "MULTIPLY" and abs(n.inputs[1].default_value - 0.36) < 1e-6)
            anim.curve(lights["beam"].node_tree, gain.inputs[1].path_from_id("default_value"), 0, FR, 0.36 * on)
        registry.append({"kind": "car", "root": root.name})

    # ---- lisses des barrières
    xi = C.ISLAND_X
    for name, y, d, ok, ck in (("lisse_entree", C.GATE_IN_Y, 1, "in_open", "in_close"), ("lisse_sortie", C.GATE_OUT_Y, -1, "out_open", "out_close")):
        arm = world.barrier_arm(M, dyn_misc, name, d)
        arm.location = (xi + d * 0.3, y, 1.13)
        ang = _arm_curve(ev, ok, ck)
        anim.curve(arm, "rotation_euler", 1, FR, -d * ang)
        registry.append({"kind": "obj", "name": name, "pad": 0.5, "active": _active_ranges(ang > 1e-4)})

    # ---- flash de la caméra ANPR (voie d'entrée)
    flash = bpy.data.lights.new("anpr_flash", "SPOT")
    flash.spot_size = math.radians(46)
    flash.spot_blend = 0.5
    flash.shadow_soft_size = 0.05
    flash.color = (0.92, 0.96, 1.0)
    _limited_falloff(flash, 7.0, 11.0)
    fo = bpy.data.objects.new("anpr_flash", flash)
    dyn_misc.objects.link(fo)
    src = Vector((xi, -24.2, 2.85))
    tgt = Vector((C.X_IN, C.GATE_IN_Y - 2.4, 0.9))
    fo.location = src
    fo.rotation_euler = (tgt - src).to_track_quat("-Z", "Y").to_euler()
    pulse = _periodic(lambda t: np.exp(-(((t - ev["flash"]) / 0.045) ** 2)))
    anim.curve(flash, "energy", 0, FR, (1900.0 if night else 5200.0) * pulse)
    ring_mat, rb = _anim_material(M, "anpr_anneau", "#eaf2ff", 0.0)
    rb.inputs["Base Color"].default_value = hex_lin("#20242b")
    anim.curve(ring_mat.node_tree, rb.inputs["Emission Strength"].path_from_id("default_value"), 0, FR, (60.0 if night else 26.0) * pulse)
    g = Geo()
    g.cyl(0, 0, 0.0, 0.012, 0.13, n=28)
    ring = g.to_object("anpr_anneau", dyn_misc, ring_mat, smooth=False)
    d = (tgt - src).normalized()
    ring.matrix_world = Matrix.Translation(src + d * 0.33) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
    registry.append({"kind": "box", "name": "flash", "min": [C.ROAD_X[0] - 1, C.GATE_IN_Y - 9.5, 0], "max": [C.ROAD_X[1] + 1.5, -22.5, 3.4], "active": _active_ranges(pulse > 2e-3)})

    # ---- cabine d'ascenseur
    cab = world.lift_cabin(M, dyn_misc)
    zc = _cabin_curve()
    anim.curve(cab, "location", 2, FR, zc)
    registry.append({"kind": "obj", "name": cab.name, "pad": 2.6 if night else 1.2, "active": [[0, C.FRAMES - 1]], "children": True})

    # ---- boucles lumineuses de la place réservée et de la place traversée
    for kind, row in (("hero", C.HERO_ROW), ("pass", C.PASS_ROW)):
        rgb, red, blue = _color_curve(ev, kind)
        mat, b = _anim_material(M, f"led_{kind}", C.STATUS["occupied"], M.led)
        for sock_name in ("Emission Color", "Base Color"):
            path = b.inputs[sock_name].path_from_id("default_value")
            anim.curves(mat.node_tree, path, FR, [rgb[:, 0], rgb[:, 1], rgb[:, 2]])
        ob = world.single_loop(M, dyn_misc, f"boucle_{kind}", C.HERO_LEVEL, row, C.HERO_COL, mat)
        base = red > 0.999 if kind == "hero" else (red < 0.001)
        registry.append({"kind": "obj", "name": ob.name, "pad": 1.0 if night else 0.5, "active": _active_ranges(~base)})

    # ---- chevrons de guidage vers la place réservée
    t0, t1 = route.when("turn_west", end=True), route.when("park")
    tt = np.linspace(t0, t1, 400)
    st = route.sample(tt)
    dist = st["dist"] - st["dist"][0]
    n_ch = int(dist[-1] // 1.9)
    z = C.ROOF_Z + 0.025 + 0.014
    blue_lin = np.array(hex_lin(C.STATUS["reserved"])[:3])
    guide_on = np.clip(_periodic(lambda t: _S((t - ev["guide_on"]) / 0.4) - _S((t - ev["parked"] + 0.6) / 0.4)), 0.0, 1.0)
    for i in range(n_ch):
        d = 1.4 + i * 1.9
        px, py, ps = (float(np.interp(d, dist, st[key])) for key in ("x", "y", "psi"))
        g = Geo()
        c, s = math.cos(ps), math.sin(ps)
        for sgn in (1, -1):  # deux barres en « > »
            pts = [(0.34, 0.0), (0.5, 0.0), (0.02, sgn * 0.5), (-0.14, sgn * 0.5)]
            g.flat([(px + a * c - b * s, py + a * s + b * c) for a, b in (pts if sgn > 0 else pts[::-1])], z)
        mat, b = _anim_material(M, f"chevron_{i}", C.STATUS["reserved"], 0.0)
        b.inputs["Base Color"].default_value = hex_lin("#59606c")
        phase = np.mod(TIME * 1.6 - i * 0.16, 1.0)  # onde qui court vers la place
        wave = 0.35 + 0.65 * np.exp(-((phase - 0.5) / 0.18) ** 2)
        strength = M.led * 1.25 * guide_on * wave
        anim.curve(mat.node_tree, b.inputs["Emission Strength"].path_from_id("default_value"), 0, FR, strength)
        bc = b.inputs["Base Color"].path_from_id("default_value")
        deck = np.array(hex_lin("#59606c")[:3])
        mixc = deck[None, :] + (blue_lin - deck)[None, :] * np.clip(guide_on, 0, 1)[:, None]
        anim.curves(mat.node_tree, bc, FR, [mixc[:, 0], mixc[:, 1], mixc[:, 2]])
        ob = g.to_object(f"chevron_{i}", dyn_misc, mat, smooth=False)
        registry.append({"kind": "obj", "name": ob.name, "pad": 0.8 if night else 0.35, "active": _active_ranges(guide_on > 1e-3)})

    scene["autopark_dyn"] = json.dumps(registry)
    scene["autopark_events"] = json.dumps({k: round(float(v), 4) for k, v in ev.items()})
    return {"route": route, "events": ev, "registry": registry, "garage": garage, "n_parked": n_parked}
