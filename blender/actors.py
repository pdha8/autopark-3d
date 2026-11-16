"""
Véhicules et éléments animés d'AutoPark 3D :
  - bibliothèque de véhicules (carrosseries de cars.py, roues, plaques), instanciée
    pour les voitures garées ;
  - la flotte en circulation (fleet.py), cadencée par traffic.py : chaque chaîne
    rejoue son trajet toutes les LOOP secondes, avec autant de véhicules identiques
    qu'il en faut pour couvrir sa durée ;
  - lisses des barrières, flash de la caméra ANPR, cabine d'ascenseur, boucles
    lumineuses des places utilisées par la flotte, chevrons de guidage.
Toutes les poses sont des fonctions du temps dans la boucle : la dernière image
rejoint exactement la première.
"""

import json
import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

import anim
import cars
import config as C
import fleet as F
import geo
import layout
import traffic
import world
from geo import Geo
from mats import hex_lin

FR = np.arange(-1, C.FRAMES + 2, dtype=float)  # images clés (une de plus de chaque côté : flou de mouvement)
TIME = FR / C.FPS
PLATE_FRAME = C.FRAMES + 60  # image hors boucle où tout est au repos : c'est elle que montre le fond
HIDE_Z = -400.0  # un véhicule hors trajet attend sous le sol du studio


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


# ------------------------------------------------------------------ bibliothèque de véhicules
# Un véhicule compte une vingtaine de pièces. Pour que la scène reste légère à mettre à jour
# (chaque rendu de zone resynchronise tous les objets), elles sont fusionnées : un maillage par
# gabarit, partagé par tous les véhicules ; seuls les matériaux (peinture, feux) changent.
def _join(objs, name, coll):
    """Fusionne des objets maillés (repère du véhicule) en un seul objet posé à l'origine."""
    sc = bpy.context.scene.collection
    target = bpy.data.objects.new(name, bpy.data.meshes.new(name))
    sc.objects.link(target)
    with bpy.context.temp_override(active_object=target, object=target, selected_objects=objs + [target], selected_editable_objects=objs + [target]):
        bpy.ops.object.join()
    geo.move_to(target, coll)
    return target


def _as_mesh(ob):
    """Objet texte -> objet maillage équivalent (même place, mêmes matériaux)."""
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    new = bpy.data.objects.new(ob.name, me)
    bpy.context.scene.collection.objects.link(new)
    new.matrix_world = ob.matrix_world.copy()
    bpy.data.objects.remove(ob, do_unlink=True)
    return new


def _mesh_copy(me, swap, name):
    """Copie d'un maillage avec des matériaux remplacés. Les matériaux restent portés par le
    maillage : deux objets qui partagent un maillage ont alors exactement les mêmes matériaux,
    et Cycles les traite comme de vraies instances (aucune resynchronisation entre deux rendus)."""
    new = me.copy()
    new.name = name
    for i, m in enumerate(new.materials):
        if m in swap:
            new.materials[i] = swap[m]
    return new


class Garage:
    def __init__(self, M, night):
        self.M = M
        self.night = night
        self.masters = geo.collection("voitures_modeles", exclude=True)
        self.wheel = wheel_mesh(M)
        self.plate_me, self.plate_band_me, self.plate_ink_me = self._plate_meshes()
        self.font = world._font(world.FONT_DIN)
        self.styles = {}  # gabarit -> carrosserie fusionnée, emplacement des plaques, roues
        self.statics = {}  # gabarit -> maillage complet d'une voiture garée
        self.painted = {}  # (gabarit, peinture) -> ce maillage, repeint
        self.plates = {}  # (gabarit, numéro) -> maillage des deux plaques
        self.base_paint = M.paint("paint_master", "#ffffff")

    def style(self, style):
        """Modèle d'un gabarit (construit à la première demande)."""
        if style not in self.styles:
            M = self.M
            mats = {"paint": self.base_paint, "roof": M["car_roof"], "glass": M["car_glass"], "chrome": M["chrome"], "dark": M["car_dark"], "lamp": M["lamp_off"], "tail": M["tail_off"], "sign": M["taxi_sign"]}
            objs, bvh = cars.build(style, mats, f"m_{style}")
            plates = [cars.plate_spot(style, bvh, rear) for rear in (False, True)]
            spec = cars.STYLES[style]
            body = _join(objs, f"m_{style}", self.masters)
            self.styles[style] = {"body": body.data, "plates": plates, "wheels": spec["wheels"], "wheel_scale": spec.get("wheel_scale", 1.0)}
        return self.styles[style]

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

    def _plate_objs(self, style, text=None):
        """Objets provisoires des deux plaques (support, bande bleue, numéro), dans le repère du véhicule."""
        sc = bpy.context.scene.collection
        out = []
        for loc, nor in self.style(style)["plates"]:
            if loc is None:
                continue
            holder = bpy.data.objects.new("plaque", self.plate_me)
            sc.objects.link(holder)
            cars._orient(holder, loc + nor * 0.003, nor)
            mw = holder.matrix_world.copy()
            band = bpy.data.objects.new("plaque_bande", self.plate_band_me)
            sc.objects.link(band)
            band.matrix_world = mw
            out += [holder, band]
            if text:
                t = geo.text("plaque_texte", text, 0.036, sc, self.M["plate_text"], font=self.font, extrude=0.0006, spacing=1.05)
                t.matrix_world = mw @ Matrix.Translation((0.012, -0.001, 0.0066))
                out.append(_as_mesh(t))
            else:
                ink = bpy.data.objects.new("plaque_encre", self.plate_ink_me)
                sc.objects.link(ink)
                ink.matrix_world = mw
                out.append(ink)
        return out

    def _wheels(self, style, coll, parent=None):
        wy, track = self.style(style)["wheels"]
        ws = self.style(style)["wheel_scale"]
        made = {}
        for fx, sx in (("G", 1), ("D", -1)):
            for fy, sy in (("av", -1), ("ar", 1)):
                w = bpy.data.objects.new(f"roue_{fy}{fx}", self.wheel)
                coll.objects.link(w)
                w.location = (sx * track, sy * wy, 0.145 * ws)
                w.scale = (ws, ws, ws)
                w.rotation_mode = "XYZ"
                w.rotation_euler = (0, 0, 0 if sx > 0 else math.pi)
                if parent is not None:
                    w.parent = parent
                made[fy + fx] = (w, sx)
        return made

    def paint_mat(self, paint):
        """Peinture : « hero », indice dans config.PAINTS, ou couleur « #rrggbb »."""
        if paint == "hero":
            return self.M["paint_hero"]
        if isinstance(paint, str):
            name = f"paint_{paint.lstrip('#')}"
            return self.M.m.get(name) or self.M.paint(name, paint)
        return self.M[f"paint_{paint}"]

    def static_car(self, name, style, paint, coll):
        """Voiture garée : un seul objet (carrosserie, roues et plaques d'un seul tenant)."""
        if style not in self.statics:
            sc = bpy.context.scene.collection
            body = bpy.data.objects.new("carrosserie", self.style(style)["body"].copy())
            sc.objects.link(body)
            wheels = [w for w, _sx in self._wheels(style, sc).values()]
            self.statics[style] = _join([body] + wheels + self._plate_objs(style), f"s_{style}", self.masters).data
        key = (style, paint)
        if key not in self.painted:
            self.painted[key] = _mesh_copy(self.statics[style], {self.base_paint: self.paint_mat(paint)}, f"s_{style}_{paint}")
        ob = bpy.data.objects.new(name, self.painted[key])
        coll.objects.link(ob)
        return ob

    def car(self, coll, name, style, paint, plate):
        """Véhicule animé : racine (pose sur la route) > caisse (roulis, tangage) + 4 roues."""
        M = self.M
        root = geo.empty(name, coll)
        root.rotation_mode = "YXZ"
        root.scale = (C.CAR_SCALE,) * 3
        body = geo.empty(name + "_caisse", coll, parent=root)
        body.rotation_mode = "YXZ"
        lamp = M["lamp_on"].copy()  # phares et feux propres à chaque véhicule : ils s'éteignent, freinent
        lamp.name = f"{name}_phare"
        tail = M["tail_on"].copy()
        tail.name = f"{name}_feu"
        swap = {self.base_paint: self.paint_mat(paint), M["lamp_off"]: lamp, M["tail_off"]: tail}
        shell = bpy.data.objects.new(name + "_carrosserie", _mesh_copy(self.style(style)["body"], swap, name + "_carrosserie"))
        coll.objects.link(shell)
        shell.parent = body
        if (style, plate) not in self.plates:
            self.plates[(style, plate)] = _join(self._plate_objs(style, plate), f"plaques_{style}_{plate}", self.masters).data
        pl = bpy.data.objects.new(name + "_plaques", self.plates[(style, plate)])
        coll.objects.link(pl)
        pl.parent = body
        wheels = self._wheels(style, coll, parent=root)
        lights = {"lamp": lamp, "tail": tail, "spots": [], "beam": None}
        if self.night:
            lights["spots"], lights["beam"] = _headlights(coll, body, name, style)
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
    BEAM_REACH = 10.0 if view == "hero" else 8.0


def lights_on(trip, tau):
    """Phares allumés (1) ou éteints (0) : ils s'éteignent quand le véhicule est garé, et en
    douceur au début et à la fin du trajet (le véhicule est alors hors de vue)."""
    tau = np.asarray(tau, dtype=float)
    on = _S(tau / 0.5) * _S((trip.T - tau) / 0.5)
    for a, b in trip.parked:
        on = on * (1.0 - (_S((tau - a - 0.7) / 0.4) - _S((tau - b + 0.9) / 0.4)))
    return on


def braking(st):
    """Feux stop (0 à 1) : en décélération, ou à l'arrêt dans la circulation."""
    v, a = st["v"], st["a"]
    return np.maximum(np.clip((-a * np.sign(v) - 0.25) / 0.8, 0.0, 1.0), (np.abs(v) < 0.05).astype(float))


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


def _cone_mesh():
    me = bpy.data.meshes.get("faisceau_cone")
    if me:
        return me
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=False, segments=40, radius1=0.62, radius2=0.0, depth=2.0)
    for v in bm.verts:
        v.co.z -= 1.0
    me = bpy.data.meshes.new("faisceau_cone")
    bm.to_mesh(me)
    bm.free()
    for poly in me.polygons:
        poly.use_smooth = True
    me.materials.append(_beam_material())
    return me


def _headlights(coll, body, name, style):
    """Renvoie (projecteurs, matériau des faisceaux) pour l'animation allumé / éteint."""
    L = cars.STYLES[style]["lamps"]
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
        cone = bpy.data.objects.new(f"{name}_faisceau{sx}", _mesh_copy(_cone_mesh(), {_beam_material(): beam}, f"{name}_faisceau{sx}"))  # pointe au phare, ouverture vers -Z
        coll.objects.link(cone)
        cone.parent = so
        cone.location = (0, 0, 0)
        cone.rotation_euler = (math.radians(9), 0, 0)
        cone.visible_shadow = False
        spots.append(spot)
    return spots, beam


# ------------------------------------------------------------------ voitures garées
def parked(garage, coll, spots, only_levels=None):
    n = 0
    for c in layout.parked_cars(spots):
        if only_levels is not None and c["level"] not in only_levels:
            continue
        ob = garage.static_car(f"garee_{c['id']}", c["style"], c["paint"], coll)
        ob.location = (c["x"], c["y"], c["z"])
        ob.rotation_euler = (0, 0, math.radians(c["heading"] + 90.0))
        ob.scale = (C.CAR_SCALE,) * 3
        n += 1
    return n


# ------------------------------------------------------------------ outils d'animation
def _S(u):
    u = np.clip(u, 0.0, 1.0)
    return u * u * u * (u * (6 * u - 15) + 10)


def window(t_on, t_off, rise=0.22, fall=0.22):
    """1 entre les instants t_on et t_off de la boucle (fronts adoucis), 0 ailleurs ; périodique."""
    t_on, t_off = t_on % C.LOOP, t_off % C.LOOP
    if t_off < t_on:
        t_off += C.LOOP
    out = np.zeros_like(TIME)
    for j in (-1, 0, 1):
        t = TIME + j * C.LOOP
        out += _S((t - t_on) / rise) - _S((t - t_off) / fall)
    return out


def pulses(times, width):
    """Somme d'impulsions brèves aux instants donnés de la boucle ; périodique."""
    out = np.zeros_like(TIME)
    for t0 in times:
        for j in (-1, 0, 1):
            out += np.exp(-(((TIME + j * C.LOOP - t0 % C.LOOP) / width) ** 2))
    return out


def _rest(values, rest=0.0):
    """Images et valeurs d'une courbe, complétées par la valeur de repos sur l'image du fond."""
    return np.concatenate([FR, [PLATE_FRAME]]), np.concatenate([np.asarray(values, dtype=float), [rest]])


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


def _sig(*arrays):
    """Empreinte par image d'un état animé (sert à réutiliser les zones déjà rendues)."""
    out = np.zeros(len(FR), dtype=np.int64)
    for a in arrays:
        out = out * 1000003 + np.round(np.asarray(a, dtype=float) * 2000.0).astype(np.int64)
    return out


# ------------------------------------------------------------------ événements de la boucle
def gate_events(fleet):
    """Passages aux barrières dans la boucle : entrées (lecture de plaque) et sorties."""
    ins, outs = [], []
    for c in fleet.chains:
        if c.has("in_clear"):
            stop = c.gate == "stop"
            flash = (c.at("gate") + 0.35) if stop else (c.at("anpr") + 0.1)
            ins.append({"chain": c.name, "plate": c.plate, "style": c.style, "stop": c.at("gate") if stop else None, "flash": flash % C.LOOP, "open": (flash + (0.45 if stop else 0.1)) % C.LOOP, "close": c.at("in_clear")})
        if c.has("out_clear"):
            outs.append({"chain": c.name, "plate": c.plate, "open": c.at("out_ramp"), "gate": c.at("out_gate"), "close": c.at("out_clear")})
    return sorted(ins, key=lambda e: e["flash"]), sorted(outs, key=lambda e: e["open"])


def bay_events(fleet):
    """Occupation des places de la flotte : {(niveau, rangée, colonne): {on, off, …}} (instants de la boucle)."""
    out = {}
    for c in fleet.chains:
        if c.bay is None:
            continue
        e = {"chain": c.name, "on": c.at("parked"), "off": c.at("bay_clear") if c.has("bay_clear") else c.at("backed")}
        if c.name == "hero":  # la place se réserve quand la voiture suivante arrive sur le toit
            e["reserved"] = (c.at("roof") + 0.4) % C.LOOP
            e["guide"] = (c.at("roof") + 0.65) % C.LOOP
        out[c.bay] = e
    return out


# ------------------------------------------------------------------ véhicules en circulation
def bake_car(chain, k, root, body, wheels):
    d = chain.d
    st = chain.state(TIME, k)
    on = st["on"] > 0
    psi, pitch = st["psi"], st["pitch"]
    cp = np.cos(pitch)
    x = st["x"] + d.axle_y * np.cos(psi) * cp
    y = st["y"] + d.axle_y * np.sin(psi) * cp
    z = np.where(on, st["z"] + d.axle_y * np.sin(pitch), HIDE_Z)
    anim.curves(root, "location", FR, [x, y, z])
    anim.curves(root, "rotation_euler", FR, [-pitch, None, psi + math.pi / 2])
    anim.curves(body, "rotation_euler", FR, [-st["dpitch"], st["droll"], None])
    spin = st["dist"] / d.wheel_r
    for key, (w, sx) in wheels.items():
        front = key.startswith("av")
        steer = st["steer"] if front else np.zeros_like(spin)
        if sx > 0:
            anim.curves(w, "rotation_euler", FR, [spin, None, steer if front else None])
        else:
            anim.curves(w, "rotation_euler", FR, [-spin, None, math.pi + steer if front else None])
    return st, on


def _bake_lights(M, night, chain, k, st, on, lights):
    tau = chain.tau(TIME, k)
    lit = lights_on(chain.trip, tau) * on
    stop = braking(st) * lit
    emission = lambda mat: next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED").inputs["Emission Strength"].path_from_id("default_value")
    tail = M.tail * (lit * (1.0 + 1.8 * stop) if night else 0.5 + 1.6 * stop)
    anim.curve(lights["tail"].node_tree, emission(lights["tail"]), 0, FR, tail)
    if night:
        anim.curve(lights["lamp"].node_tree, emission(lights["lamp"]), 0, FR, M.lamp * lit)
        for spot in lights["spots"]:
            anim.curve(spot, "energy", 0, FR, 520.0 * lit)
        gain = next(n for n in lights["beam"].node_tree.nodes if n.type == "MATH" and n.operation == "MULTIPLY" and abs(n.inputs[1].default_value - 0.36) < 1e-6)
        anim.curve(lights["beam"].node_tree, gain.inputs[1].path_from_id("default_value"), 0, FR, 0.36 * lit)
    return lit, stop


def _cabin_curve():
    """Ascenseur : P0 -> P3 -> P1 -> P0 -> P2 -> P0 sur la boucle."""
    moves = [(3.0, 5.5, 3), (14.0, 4.0, -2), (22.0, 3.0, -1), (29.0, 4.2, 2), (38.0, 4.2, -2)]  # départ, durée, niveaux
    t = np.mod(TIME, C.LOOP)
    return 0.14 + sum(dl * C.LEVEL_H * _S((t - t0) / dur) for t0, dur, dl in moves)


def build(scene, M, spots, night):
    fleet = traffic.plan()
    garage = Garage(M, night)
    n_parked = parked(garage, geo.collection("voitures_garees"), spots)
    dyn_cars = geo.collection("voitures_animees")
    dyn_misc = geo.collection("elements_animes")
    registry, sigs = [], {}

    # ---- la flotte
    for ci, chain in enumerate(fleet.chains):
        for k in range(chain.m):
            name = f"{chain.name}_{k}"
            root, body, wheels, lights = garage.car(dyn_cars, name, chain.style, chain.paint, chain.plate)
            st, on = bake_car(chain, k, root, body, wheels)
            lit, stop = _bake_lights(M, night, chain, k, st, on, lights)
            registry.append({"kind": "car", "root": root.name, "chain": ci, "k": k})
            sigs[root.name] = _sig(np.where(on, st["x"], 0.0), np.where(on, st["y"], 0.0), np.where(on, st["z"], HIDE_Z), np.where(on, st["psi"], 0.0), lit, stop)

    # ---- lisses des barrières
    ins, outs = gate_events(fleet)
    xi = C.ISLAND_X
    for name, y, d, events in (("lisse_entree", C.GATE_IN_Y, 1, ins), ("lisse_sortie", C.GATE_OUT_Y, -1, outs)):
        arm = world.barrier_arm(M, dyn_misc, name, d)
        arm.location = (xi + d * 0.3, y, 1.13)
        up = np.clip(sum(window(e["open"], e["close"], 0.7, 0.9) for e in events), 0.0, 1.0)
        anim.curve(arm, "rotation_euler", 1, *_rest(-d * math.radians(84.0) * up))
        registry.append({"kind": "obj", "name": name, "pad": 0.5, "active": _active_ranges(up > 1e-4)})
        sigs[name] = _sig(up)

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
    pulse = pulses([e["flash"] for e in ins], 0.045)
    anim.curve(flash, "energy", 0, *_rest((1900.0 if night else 5200.0) * pulse))
    ring_mat, rb = _anim_material(M, "anpr_anneau", "#eaf2ff", 0.0)
    rb.inputs["Base Color"].default_value = hex_lin("#20242b")
    anim.curve(ring_mat.node_tree, rb.inputs["Emission Strength"].path_from_id("default_value"), 0, *_rest((60.0 if night else 26.0) * pulse))
    g = Geo()
    g.cyl(0, 0, 0.0, 0.012, 0.13, n=28)
    ring = g.to_object("anpr_anneau", dyn_misc, ring_mat, smooth=False)
    d = (tgt - src).normalized()
    ring.matrix_world = Matrix.Translation(src + d * 0.33) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
    registry.append({"kind": "box", "name": "flash", "min": [C.ROAD_X[0] - 1, C.GATE_IN_Y - 9.5, 0], "max": [C.ROAD_X[1] + 1.5, -22.5, 3.4], "active": _active_ranges(pulse > 2e-3)})
    sigs["flash"] = _sig(pulse)

    # ---- cabine d'ascenseur
    cab = world.lift_cabin(M, dyn_misc)
    zc = _cabin_curve()
    anim.curve(cab, "location", 2, FR, zc)
    registry.append({"kind": "obj", "name": cab.name, "pad": 2.6 if night else 1.2, "active": [[0, C.FRAMES - 1]], "children": True})
    sigs[cab.name] = _sig(zc)

    # ---- boucles lumineuses des places de la flotte : rouge quand la voiture est là, verte sinon
    #      (place suivie par le site : bleue, « réservée », dès que la voiture suivante est sur le toit)
    cols = {k: np.array(hex_lin(v)[:3]) for k, v in C.STATUS.items()}
    bays = bay_events(fleet)
    hero = fleet.by_name["hero"]
    loops = [(key, window(e["on"], e["off"]), window(e["reserved"], e["on"]) if "reserved" in e else np.zeros_like(TIME)) for key, e in bays.items()]
    loops.append(((C.HERO_LEVEL, C.PASS_ROW, C.HERO_COL), window(hero.at("pass_in"), hero.at("pass_out")), np.zeros_like(TIME)))
    for (lv, row, col), red, blue in loops:
        red, blue = np.clip(red, 0, 1), np.clip(blue, 0, 1)
        green = np.clip(1 - red - blue, 0, 1)
        rgb = red[:, None] * cols["occupied"] + blue[:, None] * cols["reserved"] + green[:, None] * cols["available"]
        sid = C.spot_id(lv, row, col)
        mat, b = _anim_material(M, f"led_{sid}", C.STATUS["available"], M.led)
        for sock_name in ("Emission Color", "Base Color"):
            path = b.inputs[sock_name].path_from_id("default_value")
            for i in range(3):
                anim.curve(mat.node_tree, path, i, *_rest(rgb[:, i], cols["available"][i]))
        ob = world.single_loop(M, dyn_misc, f"boucle_{sid}", lv, row, col, mat)
        registry.append({"kind": "obj", "name": ob.name, "pad": 1.0 if night else 0.5, "active": _active_ranges(green < 0.999)})
        sigs[ob.name] = _sig(red, blue)

    # ---- chevrons de guidage vers la place suivie
    run = hero.trip.legs[0].run
    qa, qb = hero.trip.marks["guide_a"][1], hero.trip.marks["guide_b"][1]
    n_ch = int((qb - qa) // 1.9)
    z = C.ROOF_Z + 0.025 + 0.014
    blue_lin = np.array(hex_lin(C.STATUS["reserved"])[:3])
    deck = np.array(hex_lin("#59606c")[:3])
    guide_on = np.clip(window(bays[hero.bay]["guide"], hero.at("parked") - 0.6, 0.4, 0.4), 0.0, 1.0)
    wave_hz = round(1.6 * C.LOOP) / C.LOOP  # un nombre entier d'ondes par boucle
    for i in range(n_ch):
        p = run.at(qa + 1.4 + i * 1.9)
        px, py, ps = float(p["x"]), float(p["y"]), float(p["heading"])
        g = Geo()
        c, s = math.cos(ps), math.sin(ps)
        for sgn in (1, -1):  # deux barres en « > »
            pts = [(0.34, 0.0), (0.5, 0.0), (0.02, sgn * 0.5), (-0.14, sgn * 0.5)]
            g.flat([(px + a * c - b * s, py + a * s + b * c) for a, b in (pts if sgn > 0 else pts[::-1])], z)
        mat, b = _anim_material(M, f"chevron_{i}", C.STATUS["reserved"], 0.0)
        b.inputs["Base Color"].default_value = hex_lin("#59606c")
        phase = np.mod(TIME * wave_hz - i * 0.16, 1.0)  # onde qui court vers la place
        strength = M.led * 1.25 * guide_on * (0.35 + 0.65 * np.exp(-((phase - 0.5) / 0.18) ** 2))
        anim.curve(mat.node_tree, b.inputs["Emission Strength"].path_from_id("default_value"), 0, *_rest(strength))
        bc = b.inputs["Base Color"].path_from_id("default_value")
        mixc = deck[None, :] + (blue_lin - deck)[None, :] * guide_on[:, None]
        for j in range(3):
            anim.curve(mat.node_tree, bc, j, *_rest(mixc[:, j], deck[j]))
        ob = g.to_object(f"chevron_{i}", dyn_misc, mat, smooth=False)
        registry.append({"kind": "obj", "name": ob.name, "pad": 0.8 if night else 0.35, "active": _active_ranges(guide_on > 1e-3)})
        sigs[ob.name] = _sig(strength, guide_on)

    scene["autopark_dyn"] = json.dumps(registry)
    return {"fleet": fleet, "registry": registry, "sigs": sigs, "garage": garage, "n_parked": n_parked, "gate": (ins, outs), "bays": bays}
