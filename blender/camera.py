"""
Caméras (mathématiques pures, utilisables hors de Blender) : position à partir
d'une cible / azimut / élévation, et projection d'un point du monde dans le cadre
vidéo. Mêmes conventions que la caméra Blender (capteur 36 mm, ajustement horizontal).
"""

import math

import config as C

SENSOR = 36.0


def _norm(v):
    n = math.sqrt(sum(a * a for a in v))
    return tuple(a / n for a in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


class View:
    def __init__(self, name, spec=None):
        self.name = name
        s = spec or C.VIEWS[name]
        self.target = tuple(s["target"])
        az, el = math.radians(s["az"]), math.radians(s["el"])
        d = s["dist"]
        self.lens = s["lens"]
        self.pos = (
            self.target[0] + d * math.cos(el) * math.cos(az),
            self.target[1] - d * math.cos(el) * math.sin(az),
            self.target[2] + d * math.sin(el),
        )
        self.fwd = _norm(tuple(t - p for t, p in zip(self.target, self.pos)))
        self.right = _norm(_cross(self.fwd, (0.0, 0.0, 1.0)))
        self.up = _cross(self.right, self.fwd)
        self.aspect = C.FRAME_W / C.FRAME_H
        self.k = self.lens / (SENSOR / 2)

    def project(self, p):
        """Point du monde -> (u, v, profondeur) ; u, v dans [0, 1], origine en bas à gauche."""
        d = (p[0] - self.pos[0], p[1] - self.pos[1], p[2] - self.pos[2])
        z = _dot(d, self.fwd)
        x = _dot(d, self.right) * self.k / z
        y = _dot(d, self.up) * self.k / z * self.aspect
        return (x + 1) / 2, (y + 1) / 2, z

    def stage(self, p):
        """Point du monde -> coordonnées maquette (x, y en unités, origine en haut à gauche
        de la maquette 1280 x 776 centrée dans le cadre)."""
        u, v, _ = self.project(p)
        return (
            u * C.FRAME_W - (C.FRAME_W - C.STAGE_W) / 2,
            (1 - v) * C.FRAME_H - (C.FRAME_H - C.STAGE_H) / 2,
        )

    def metres_per_unit(self):
        """Taille d'une unité de maquette au niveau de la cible (m)."""
        d = math.dist(self.pos, self.target)
        return (SENSOR / self.lens) * d / C.FRAME_W
