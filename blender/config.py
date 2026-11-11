"""
AutoPark 3D — dimensions, couleurs et réglages partagés par toute la chaîne
(construction de la scène, animation, rendu, export des données du site).

Unités : mètres. Repère Blender : Z en haut, façade principale au sud (y négatif),
tour de rampe à l'est (x positif). La caméra regarde depuis le sud-est.
"""

import math

# ----------------------------------------------------------------- boucle
FPS = 60
LOOP = 12.0  # durée de la boucle (s)
FRAMES = int(FPS * LOOP)  # 720 images
N_CARS = 7  # voitures identiques qui se relaient : trajet complet = N_CARS * LOOP

# ----------------------------------------------------------------- voitures
CAR_SCALE = 2.2  # les modèles de cars.py sont en « unités jouet »
WHEEL_R = 0.145 * CAR_SCALE

# ----------------------------------------------------------------- bâtiment
SPOT_W = 2.7
SPOT_D = 5.0
AISLE = 6.0
END_AISLE = 6.0
NCOL = 15
NROW = 4  # rangées A, B, C, D (du sud au nord)
NLEV = 4  # P0 … P3 (P3 = toit à ciel ouvert)
BX = NCOL * SPOT_W / 2 + END_AISLE  # demi-longueur : 26.25
BY = (NROW * SPOT_D + 2 * AISLE) / 2  # demi-profondeur : 16
LEVEL_H = 3.9
SLAB = 0.30
ROOF_Z = (NLEV - 1) * LEVEL_H  # 11.7

# rangée -> (y du bord côté allée, y du fond, cap de la voiture garée en degrés)
#   A : nez au sud (vers la façade)   B : nez au nord
#   C : nez au sud                    D : nez au nord
ROWS = {
    0: {"name": "A", "y0": -BY, "y1": -BY + SPOT_D, "heading": 270.0, "aisle_y": -BY + SPOT_D},
    1: {"name": "B", "y0": -BY + SPOT_D + AISLE, "y1": 0.0, "heading": 90.0, "aisle_y": -BY + SPOT_D + AISLE},
    2: {"name": "C", "y0": 0.0, "y1": SPOT_D, "heading": 270.0, "aisle_y": SPOT_D},
    3: {"name": "D", "y0": SPOT_D + AISLE, "y1": BY, "heading": 90.0, "aisle_y": SPOT_D + AISLE},
}
AISLE1 = (-BY + SPOT_D, -BY + SPOT_D + AISLE)  # (-11, -5)
AISLE2 = (SPOT_D, SPOT_D + AISLE)  # (5, 11)


def spot_x(col):
    return -BX + END_AISLE + (col + 0.5) * SPOT_W


def spot_center(row, col):
    r = ROWS[row]
    return spot_x(col), (r["y0"] + r["y1"]) / 2


def spot_id(level, row, col):
    return f"P{level}-{row * NCOL + col + 1:03d}"


# ----------------------------------------------------------------- tour de rampe
TOWER = (37.0, -14.5)
R_UP = 8.2  # voie extérieure : montée (sens anti-horaire)
R_DN = 4.8  # voie intérieure : descente (sens horaire)
R_IN = 3.2
R_OUT = 10.2
TURNS = 2.25
PITCH = ROOF_Z / TURNS  # 5.2 m par tour
TH_END = 360.0 * TURNS  # 810°

X_IN = TOWER[0] + R_UP  # 45.2 : voie d'entrée (vers le nord)
X_OUT = TOWER[0] + R_DN  # 41.8 : voie de sortie (vers le sud)
Y_TAN = TOWER[1]  # -14.5 : points de tangence au sol
Y_WEST = TOWER[1] + R_UP  # -6.3 : voie vers l'ouest sur le toit (arrivée)
Y_EAST = TOWER[1] + R_DN  # -9.7 : voie vers l'est sur le toit (départ)

ROAD_X = (X_OUT - 2.1, X_IN + 2.1)  # 39.7 … 47.3
GATE_IN_Y = -27.0  # lisse d'entrée
GATE_OUT_Y = -25.4  # lisse de sortie
ISLAND_X = (X_IN + X_OUT) / 2  # 43.5

# ----------------------------------------------------------------- place « héros » (toit)
# La voiture arrive par l'allée nord, se gare en rangée C (nez au sud), puis repart
# en marche avant à travers la place d'en face (rangée B, toujours libre).
HERO_LEVEL, HERO_ROW, HERO_COL = 3, 2, 8
HERO_X = spot_x(HERO_COL)  # 2.7
PARK_Y = 2.5 + 0.53 * CAR_SCALE  # y de l'essieu arrière une fois garé (nez au sud)
PASS_ROW = 1  # place traversée au départ (même colonne, rangée B)
Y_A2_WEST = AISLE2[0] + 4.5  # 9.5 : voie vers l'ouest de l'allée nord
X_NORTH = BX - 2.4  # 23.85 : voie vers le nord de l'allée d'extrémité est
R_BRIDGE = 3.5
R_TURN = 4.0

# ----------------------------------------------------------------- socle
BASE = (-31.0, 52.5, -32.0, 20.5)  # x0, x1, y0, y1
BASE_T = 0.5
ROAD_END_Y = -150.0

# ----------------------------------------------------------------- couleurs (sRGB hex)
PAGE_DAY = "#e9edf2"
PAGE_NIGHT = "#0a0e1a"
ACCENT = "#2563eb"
CYAN = "#64c8ff"
STATUS = {
    "available": "#4ade80",
    "occupied": "#f87171",
    "reserved": "#60a5fa",
    "selected": "#facc15",
    "ev": "#34d399",
    "pmr": "#818cf8",
    "family": "#fb923c",
}

# peintures des voitures garées : (nom, hex, poids)
PAINTS = [
    ("blanc", "#f4f5f7", 26),
    ("perle", "#dfe3e8", 12),
    ("argent", "#aeb5bf", 14),
    ("graphite", "#444a55", 13),
    ("noir", "#16181d", 8),
    ("sable", "#d9c7a8", 6),
    ("sauge", "#8fae9b", 6),
    ("brique", "#c8624a", 5),
    ("moutarde", "#e2b144", 4),
    ("marine", "#27375e", 6),
]
STYLES = ["mini", "sedan", "hatch"]

# ----------------------------------------------------------------- vues (caméras)
# cible, azimut (0 = vu depuis l'est, 90 = vu depuis le sud), élévation, distance, focale
VIEWS = {
    "hero": {"target": (5.4, -9.7, 3.0), "az": 52.0, "el": 29.0, "dist": 460.0, "lens": 112.0},
    "gate": {"target": (37.1, -27.2, 0.5), "az": 64.0, "el": 20.0, "dist": 160.0, "lens": 200.0},
    "roof": {"target": (1.0, -2.1, ROOF_Z + 0.4), "az": 58.0, "el": 34.0, "dist": 200.0, "lens": 205.0},
}
FRAME_W, FRAME_H = 1760, 960  # cadre vidéo en unités de maquette (maquette 1280 x 776 + marges)
STAGE_W, STAGE_H = 1280, 776


def deg(a):
    return math.radians(a)
