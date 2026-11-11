"""
Plan d'occupation du parking (240 places) : type de place, état initial, voiture.
Déterministe (graine fixe) : la scène Blender et le site partent du même état
(89 disponibles, 108 occupées, 43 réservées, comme le prototype).
"""

import random

import config as C

# niveau -> (occupées, réservées)
TARGETS = {0: (28, 9), 1: (26, 11), 2: (24, 11), 3: (30, 12)}
LETTERS = "ABCDEFGHJKLMNPQRSTVWXYZ"


def spot_type(level, row, col):
    if level != 0:
        return "std"
    if row == 0 and col <= 3:
        return "pmr"
    if row == 0 and 5 <= col <= 12:
        return "ev"
    if row == 1 and col <= 3:
        return "family"
    return "std"


def _plate(rng):
    l = lambda: rng.choice(LETTERS)
    d = lambda: rng.randint(0, 9)
    return f"{l()}{l()}-{d()}{d()}{d()}-{l()}{l()}"


def make(seed=11):
    rng = random.Random(seed)
    paints = [i for i, p in enumerate(C.PAINTS) for _ in range(p[2])]
    spots = []
    for level in range(C.NLEV):
        cells = [(r, c) for r in range(C.NROW) for c in range(C.NCOL)]
        fixed = {}
        if level == C.HERO_LEVEL:
            fixed[(C.HERO_ROW, C.HERO_COL)] = "occupied"  # la voiture « héros » y est garée au début de la boucle
            fixed[(C.PASS_ROW, C.HERO_COL)] = "available"  # place traversée au départ
            fixed[(C.PASS_ROW, C.HERO_COL + 1)] = "available"  # vue dégagée sur la place
            fixed[(C.HERO_ROW, C.HERO_COL - 1)] = "reserved"  # côté du virage d'entrée : dégagé
            fixed[(C.HERO_ROW, C.HERO_COL + 1)] = "occupied"
            fixed[(C.PASS_ROW, C.HERO_COL - 1)] = "occupied"
            fixed[(0, C.HERO_COL)] = "occupied"
            fixed[(3, C.NCOL - 1)] = "available"  # angle nord-est : dégagé pour le virage vers l'allée nord
        n_occ, n_res = TARGETS[level]
        status = dict(fixed)
        free = [c for c in cells if c not in status]
        # la rangée A (visible depuis la façade) est plus remplie
        weight = lambda cell: 1.7 if cell[0] == 0 else 1.0
        need = n_occ - sum(1 for s in status.values() if s == "occupied")
        for _ in range(need):
            cell = rng.choices(free, weights=[weight(c) for c in free])[0]
            free.remove(cell)
            status[cell] = "occupied"
        for cell in rng.sample(free, n_res - sum(1 for v in fixed.values() if v == "reserved")):
            free.remove(cell)
            status[cell] = "reserved"
        for cell in free:
            status[cell] = "available"
        for row, col in cells:
            hero = level == C.HERO_LEVEL and (row, col) == (C.HERO_ROW, C.HERO_COL)
            x, y = C.spot_center(row, col)
            spots.append(
                {
                    "id": C.spot_id(level, row, col),
                    "level": level,
                    "row": row,
                    "col": col,
                    "type": spot_type(level, row, col),
                    "status": status[(row, col)],
                    "x": round(x, 3),
                    "y": round(y, 3),
                    "heading": C.ROWS[row]["heading"],
                    "style": "mini" if hero else rng.choice(C.STYLES),
                    "paint": -1 if hero else rng.choice(paints),
                    "plate": "AB-123-CD" if hero else _plate(rng),
                    "hero": hero,
                }
            )
    return spots


def counts(spots):
    out = {"available": 0, "occupied": 0, "reserved": 0}
    for s in spots:
        out[s["status"]] += 1
    return out


if __name__ == "__main__":
    sp = make()
    print(counts(sp), len(sp))
    for level in range(C.NLEV):
        for row in range(C.NROW - 1, -1, -1):
            line = "".join({"available": ".", "occupied": "#", "reserved": "r"}[s["status"]] for s in sp if s["level"] == level and s["row"] == row)
            print(f"P{level} {C.ROWS[row]['name']} {line}")
