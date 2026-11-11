"""Matériaux de la maquette (jour / nuit)."""

import bpy

import config as C


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_lin(h, a=1.0):
    h = h.lstrip("#")
    return tuple(srgb_to_linear(int(h[i : i + 2], 16) / 255) for i in (0, 2, 4)) + (a,)


def _set(node, names, value):
    for name in names if isinstance(names, (list, tuple)) else [names]:
        if name in node.inputs:
            node.inputs[name].default_value = value
            return True
    return False


class Mats:
    def __init__(self, night):
        self.night = night
        self.m = {}
        # intensités lumineuses (jour, nuit)
        pick = lambda d, n: n if night else d
        self.led = pick(1.9, 9.0)  # boucles des places
        self.ceiling = pick(5.0, 30.0)  # réglettes des niveaux couverts
        self.sign = pick(1.6, 3.2)  # enseignes, écrans
        self.lamp = pick(0.0, 26.0)  # phares des voitures qui roulent
        self.tail = pick(0.7, 7.0)
        self.street = pick(0.0, 30.0)  # lampadaires
        self.accent_line = pick(1.2, 12.0)  # bandeau de la rampe
        self._build()

    # ------------------------------------------------------------ fabriques
    def pbr(self, name, color, rough=0.6, metal=0.0, coat=0.0, coat_rough=0.1, spec=0.5, emit=None, strength=0.0):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        b = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        _set(b, "Base Color", hex_lin(color) if isinstance(color, str) else color)
        _set(b, "Roughness", rough)
        _set(b, "Metallic", metal)
        _set(b, ["Coat Weight", "Coat"], coat)
        _set(b, "Coat Roughness", coat_rough)
        _set(b, ["Specular IOR Level", "Specular"], spec)
        if emit is not None:
            _set(b, ["Emission Color", "Emission"], hex_lin(emit) if isinstance(emit, str) else emit)
            _set(b, "Emission Strength", strength)
        self.m[name] = mat
        return mat

    def glow(self, name, color, strength, base=None):
        """Surface lumineuse : couleur visible de jour, lumière la nuit."""
        return self.pbr(name, base or color, rough=0.45, emit=color, strength=strength)

    def glass(self, name, tint="#dfeaf2", reflect=0.14, rough=0.03):
        """Vitrage d'architecture : laisse passer la lumière (pas de caustiques), reflets légers."""
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        mix = nt.nodes.new("ShaderNodeMixShader")
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        gl = nt.nodes.new("ShaderNodeBsdfGlossy")
        lw = nt.nodes.new("ShaderNodeLayerWeight")
        mr = nt.nodes.new("ShaderNodeMapRange")
        tr.inputs["Color"].default_value = hex_lin(tint)
        gl.inputs["Roughness"].default_value = rough
        lw.inputs["Blend"].default_value = 0.35
        mr.inputs["To Min"].default_value = reflect * 0.4
        mr.inputs["To Max"].default_value = min(1.0, reflect * 4.0)
        nt.links.new(lw.outputs["Fresnel"], mr.inputs["Value"])
        nt.links.new(mr.outputs["Result"], mix.inputs["Fac"])
        nt.links.new(tr.outputs["BSDF"], mix.inputs[1])
        nt.links.new(gl.outputs["BSDF"], mix.inputs[2])
        nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
        self.m[name] = mat
        return mat

    def paint(self, name, color):
        return self.pbr(name, color, rough=0.3, coat=0.65, coat_rough=0.08)

    def __getitem__(self, name):
        return self.m[name]

    # ------------------------------------------------------------ catalogue
    def _build(self):
        n = self.night
        # structure
        self.pbr("concrete", "#dcdedc", rough=0.82)
        self.pbr("concrete_dark", "#b4b8bb", rough=0.85)
        self.pbr("wall", "#c3c8cc", rough=0.85)
        self.pbr("core", "#363d4a", rough=0.7)
        self.pbr("deck", "#59606c", rough=0.5, spec=0.45)
        self.pbr("base", "#2f343d", rough=0.88)
        self.pbr("road", "#262a32", rough=0.8)
        self.pbr("paving", "#c6cbd1", rough=0.8)
        self.pbr("lawn", "#8fcc8d", rough=1.0, spec=0.1)
        self.pbr("hedge", "#5aa46c", rough=1.0, spec=0.1)
        self.pbr("leaf_a", "#5cb276", rough=0.95, spec=0.15)
        self.pbr("leaf_b", "#86cc8a", rough=0.95, spec=0.15)
        self.pbr("trunk", "#8d6e55", rough=0.9)
        self.pbr("mark", "#eef1f4", rough=0.6)  # peinture blanche au sol
        self.pbr("mark_dim", "#99a1ac", rough=0.6)
        self.pbr("metal", "#cdd2d8", rough=0.35, metal=0.9)
        self.pbr("metal_dark", "#3b4049", rough=0.4, metal=0.7)
        self.pbr("white", "#f3f4f6", rough=0.4, coat=0.3)
        self.pbr("accent", C.ACCENT, rough=0.38, coat=0.4, coat_rough=0.1)
        self.pbr("red", "#e5484d", rough=0.4, coat=0.3)
        self.glass("glass")
        self.glass("glass_blue", tint="#e3eef8", reflect=0.1)
        # lumières
        self.glow("ceiling", "#eef4ff", self.ceiling, base="#f2f4f6")
        self.glow("accent_line", C.CYAN, self.accent_line)
        self.glow("street", "#ffdfb0", self.street, base="#f5f1e8")
        self.glow("cabin_light", "#ffe9c4", 7.0 if n else 1.5, base="#f5f1e8")
        self.glow("sign_white", "#f4f8ff", self.sign * 1.5, base="#f1f3f5")
        self.glow("sign_blue", C.ACCENT, self.sign * 1.4)
        self.glow("sign_green", "#16a34a", self.sign * 0.75)
        self.glow("sign_red", "#dc2626", self.sign * 0.75)
        for key, col in C.STATUS.items():
            self.glow(f"led_{key}", col, self.led)
            self.pbr(f"pad_{key}", col, rough=0.7)
        self.glow("screen", "#34d399", self.sign * 1.5)
        # voitures
        self.pbr("car_glass", "#0c1422", rough=0.06, coat=1.0, coat_rough=0.03)
        self.pbr("chrome", "#e9ebee", rough=0.14, metal=1.0)
        self.pbr("car_dark", "#1d2026", rough=0.5)
        self.pbr("rubber", "#15161a", rough=0.78, spec=0.3)
        self.pbr("rim", "#c9ced4", rough=0.3, metal=0.85)
        self.pbr("car_roof", "#f6f7f9", rough=0.3, coat=0.6, coat_rough=0.08)
        self.pbr("plate", "#f4f5f6", rough=0.4)
        self.pbr("plate_blue", "#1d4ed8", rough=0.4)
        self.pbr("plate_text", "#14161a", rough=0.5)
        self.pbr("lamp_off", "#f4f6f8", rough=0.12, coat=1.0)
        self.pbr("tail_off", "#b3262b", rough=0.25, coat=0.8)
        self.pbr("lamp_on", "#fbfcff", rough=0.12, coat=1.0, emit="#fff1d6", strength=self.lamp)
        self.pbr("tail_on", "#d42a2f", rough=0.25, coat=0.8, emit="#ff2a2a", strength=self.tail)
        self.paint("paint_hero", C.ACCENT)
        for i, (name, col, _w) in enumerate(C.PAINTS):
            self.paint(f"paint_{i}", col)
