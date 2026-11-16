"""
Plan d'occupation du parking (240 places) : type de place, état initial, voiture.
Déterministe (graine fixe) : la scène Blender et le site partent du même état
(89 disponibles, 108 occupées, 43 réservées, comme le prototype).

Les places utilisées par la flotte en circulation (fleet.py) n'ont pas de voiture
fixe : « dyn » y vaut le nom de la chaîne. Celles qui doivent rester dégagées
(virages, traversée) sont vidées ; une place cachée du même niveau est occupée à
leur place, pour garder les mêmes totaux.
"""

import random

import config as C
import fleet as F

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
                    "dyn": None,
                }
            )
    _reserve_for_traffic(spots)
    return spots


def _reserve_for_traffic(spots):
    by = {(s["level"], s["row"], s["col"]): s for s in spots}
    dyn, clear = F.bays(), F.clear_bays()
    rng = random.Random(23)
    for s in spots:  # gabarits supplémentaires (tirage indépendant du reste)
        if rng.random() < C.EXTRA_SHARE and not s["hero"]:
            s["style"] = rng.choice(C.EXTRA_STYLES)
    for key in sorted(set(dyn) | clear):
        s = by[key]
        if key in dyn:
            s["dyn"] = dyn[key]
        if s["status"] != "occupied" or s["hero"]:
            continue
        # la voiture fixe déménage vers une place libre du même niveau, loin des façades
        lv = key[0]
        pool = [c for c in spots if c["level"] == lv and c["status"] == "available" and (c["level"], c["row"], c["col"]) not in dyn and (c["level"], c["row"], c["col"]) not in clear and (lv == C.HERO_LEVEL or c["row"] in (1, 2))]
        pool = pool or [c for c in spots if c["level"] == lv and c["status"] == "available" and (c["level"], c["row"], c["col"]) not in dyn and (c["level"], c["row"], c["col"]) not in clear]
        t = rng.choice(pool)
        t["status"], s["status"] = "occupied", "available"
    # une place de la flotte est libre (verte) quand le véhicule n'y est pas : sa réservation déménage
    for key in sorted(dyn):
        s = by[key]
        if s["status"] == "reserved" and not s["hero"]:
            lv = key[0]
            pool = [c for c in spots if c["level"] == lv and c["status"] == "available" and (lv, c["row"], c["col"]) not in dyn and (lv, c["row"], c["col"]) not in clear]
            rng.choice(pool)["status"] = "reserved"
            s["status"] = "available"


def parked_cars(spots):
    """Voitures garées fixes : position (centre), cap du nez en degrés, altitude."""
    rng = random.Random(5)
    out = []
    for s in spots:
        dx, dy, da = rng.uniform(-0.13, 0.13), rng.uniform(-0.22, 0.18), rng.uniform(-2.2, 2.2)
        if s["status"] != "occupied" or s["hero"] or s["dyn"]:
            continue
        z = s["level"] * C.LEVEL_H + (0.04 if s["level"] == 0 else 0.025)
        out.append({"id": s["id"], "level": s["level"], "x": s["x"] + dx, "y": s["y"] + dy, "z": z, "heading": s["heading"] + da, "style": s["style"], "paint": s["paint"]})
    return out


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
