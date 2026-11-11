"""
Petits outils de modélisation (bmesh) : boîtes, cylindres, prismes, bandes,
texte… regroupés dans un seul maillage par objet, avec arêtes arrondies
(biseau) et normales pondérées pour un rendu « maquette ».
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector


def rrect(x0, x1, y0, y1, r, n=6):
    """Contour d'un rectangle à coins arrondis (sens anti-horaire)."""
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    if r <= 1e-6:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    pts = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def circle(cx, cy, r, n=48, a0=0.0, a1=360.0):
    full = abs(a1 - a0) >= 360.0
    m = n if full else n + 1
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(m)]


class Geo:
    """Accumule de la géométrie dans un seul maillage."""

    def __init__(self):
        self.bm = bmesh.new()

    # ------------------------------------------------------------ primitives
    def _face(self, verts, mat):
        try:
            f = self.bm.faces.new(verts)
            f.material_index = mat
            return f
        except ValueError:
            return None

    def box(self, x0, x1, y0, y1, z0, z1, mat=0, rot=0.0, pivot=None):
        """Boîte alignée sur les axes, éventuellement tournée de rot degrés autour de Z (pivot)."""
        co = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        if rot:
            px, py = pivot if pivot else ((x0 + x1) / 2, (y0 + y1) / 2)
            c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
            co = [(px + (x - px) * c - (y - py) * s, py + (x - px) * s + (y - py) * c, z) for x, y, z in co]
        v = [self.bm.verts.new(p) for p in co]
        for idx in ((3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            self._face([v[i] for i in idx], mat)

    def prism(self, pts, z0, z1, mat=0, top_mat=None):
        """Prisme droit de contour pts (sens anti-horaire, éventuellement concave)."""
        lo = [self.bm.verts.new((x, y, z0)) for x, y in pts]
        hi = [self.bm.verts.new((x, y, z1)) for x, y in pts]
        n = len(pts)
        self._face(list(reversed(lo)), mat)
        self._face(hi, mat if top_mat is None else top_mat)
        for i in range(n):
            j = (i + 1) % n
            self._face([lo[i], lo[j], hi[j], hi[i]], mat)

    def cyl(self, cx, cy, z0, z1, r, n=32, mat=0, r_top=None):
        rt = r if r_top is None else r_top
        lo = [self.bm.verts.new((cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z0)) for i in range(n)]
        hi = [self.bm.verts.new((cx + rt * math.cos(2 * math.pi * i / n), cy + rt * math.sin(2 * math.pi * i / n), z1)) for i in range(n)]
        self._face(list(reversed(lo)), mat)
        self._face(hi, mat)
        for i in range(n):
            j = (i + 1) % n
            self._face([lo[i], lo[j], hi[j], hi[i]], mat)

    def flat(self, pts, z, mat=0):
        """Polygone plat (peinture au sol), face vers le haut."""
        self._face([self.bm.verts.new((x, y, z)) for x, y in pts], mat)

    def band(self, inner, outer, z, mat=0, closed=True):
        """Bande plate entre deux contours de même longueur (boucle lumineuse d'une place)."""
        a = [self.bm.verts.new((x, y, z)) for x, y in inner]
        b = [self.bm.verts.new((x, y, z)) for x, y in outer]
        n = len(a)
        for i in range(n if closed else n - 1):
            j = (i + 1) % n
            self._face([b[i], b[j], a[j], a[i]], mat)

    def tube(self, path, r, n=10, mat=0):
        """Tube le long d'une suite de points 3D (fil, main courante, bandeau lumineux)."""
        rings = []
        for i, p in enumerate(path):
            p = Vector(p)
            a = Vector(path[max(i - 1, 0)])
            b = Vector(path[min(i + 1, len(path) - 1)])
            t = (b - a).normalized()
            up = Vector((0, 0, 1)) if abs(t.z) < 0.95 else Vector((1, 0, 0))
            u = t.cross(up).normalized()
            w = t.cross(u).normalized()
            rings.append([self.bm.verts.new(p + r * (math.cos(2 * math.pi * k / n) * u + math.sin(2 * math.pi * k / n) * w)) for k in range(n)])
        for ra, rb in zip(rings, rings[1:]):
            for k in range(n):
                j = (k + 1) % n
                self._face([ra[k], ra[j], rb[j], rb[k]], mat)
        self._face(rings[0], mat)
        self._face(list(reversed(rings[-1])), mat)

    def grid(self, rows, mat=0, flip=False):
        """Surface réglée : rows = liste de rangées de points 3D de même longueur."""
        vs = [[self.bm.verts.new(p) for p in row] for row in rows]
        for a, b in zip(vs, vs[1:]):
            for i in range(len(a) - 1):
                q = [a[i], a[i + 1], b[i + 1], b[i]]
                self._face(list(reversed(q)) if flip else q, mat)
        return vs

    # ------------------------------------------------------------ sortie
    def to_object(self, name, coll, mats, bevel=0.0, segments=3, smooth=True, angle=35.0, weighted=True):
        bm = self.bm
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        for m in mats if isinstance(mats, (list, tuple)) else [mats]:
            me.materials.append(m)
        ob = bpy.data.objects.new(name, me)
        coll.objects.link(ob)
        if smooth:
            for p in me.polygons:
                p.use_smooth = True
        if bevel > 0:
            mod = ob.modifiers.new("biseau", "BEVEL")
            mod.width = bevel
            mod.segments = segments
            mod.limit_method = "ANGLE"
            mod.angle_limit = math.radians(angle)
            mod.miter_outer = "MITER_ARC"
        if smooth and weighted:
            wn = ob.modifiers.new("normales", "WEIGHTED_NORMAL")
            wn.keep_sharp = True
            wn.weight = 60
        if smooth and bevel <= 0:
            try:
                me.set_sharp_from_angle(angle=math.radians(angle))
            except Exception:
                pass
        return ob


def text(name, body, size, coll, mat, font=None, extrude=0.0, align="CENTER", spacing=1.0, bevel=0.0):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    cu.align_x = align
    cu.align_y = "CENTER"
    cu.extrude = extrude
    cu.space_character = spacing
    cu.bevel_depth = bevel
    cu.resolution_u = 6
    if font is not None:
        cu.font = font
    cu.materials.append(mat)
    ob = bpy.data.objects.new(name, cu)
    coll.objects.link(ob)
    return ob


def place(ob, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
    """rot en degrés (XYZ)."""
    ob.location = loc
    ob.rotation_euler = tuple(math.radians(a) for a in rot)
    ob.scale = scale
    return ob


def collection(name, parent=None, exclude=False):
    coll = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(coll)
    if exclude:
        lc = _find_layer_collection(bpy.context.view_layer.layer_collection, coll)
        if lc:
            lc.exclude = True
    return coll


def _find_layer_collection(lc, coll):
    if lc.collection == coll:
        return lc
    for child in lc.children:
        r = _find_layer_collection(child, coll)
        if r:
            return r
    return None


def move_to(ob, coll):
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    coll.objects.link(ob)


def empty(name, coll, parent=None):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_size = 0.5
    coll.objects.link(ob)
    if parent is not None:
        ob.parent = parent
    return ob


def instance(name, src, coll, loc, rot_z=0.0, scale=1.0):
    ob = bpy.data.objects.new(name, None)
    ob.instance_type = "COLLECTION"
    ob.instance_collection = src
    ob.location = loc
    ob.rotation_euler = (0, 0, math.radians(rot_z))
    ob.scale = (scale, scale, scale)
    coll.objects.link(ob)
    return ob
