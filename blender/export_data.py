"""
Exporte vers le site les données calculées avec la scène 3D :
  src/data/layout.json : les 240 places (type, état initial, plaque)
  src/data/sync.json   : boucle, instants clés (barrières, flash, états de la place
                         réservée) et ancrages des étiquettes par vue (coordonnées de la
                         maquette 1280 x 776).

  blender -b --factory-startup -P blender/export_data.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import actors  # noqa: E402
import config as C  # noqa: E402
import layout  # noqa: E402
import route as R  # noqa: E402
from camera import View  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "src", "data")


def main():
    os.makedirs(OUT, exist_ok=True)
    route = actors.get_route()
    ev = actors.timeline(route)
    spots = layout.make()
    hero = next(s for s in spots if s["hero"])
    keep = ("id", "level", "row", "col", "type", "status", "plate", "style", "paint", "hero")
    json.dump(
        {"levels": C.NLEV, "rows": C.NROW, "cols": C.NCOL, "rate": 3.5, "paints": [p[1] for p in C.PAINTS], "accent": C.ACCENT, "spots": [{k: s[k] for k in keep} for s in spots]},
        open(os.path.join(OUT, "layout.json"), "w"),
        separators=(",", ":"),
    )

    w = route.when
    times = dict(ev)
    times.update({"stop": w("stop"), "go": w("gate_to_ramp"), "ramp_in": w("up_a"), "roof_in": w("bridge"), "turn_in": w("turn_in"), "exit_gate": w("exit_gate"), "exit_ramp": w("exit_slow")})
    sync = {
        "fps": C.FPS,
        "loop": C.LOOP,
        "frames": C.FRAMES,
        "cars": C.N_CARS,
        "plate": hero["plate"],
        "bay": hero["id"],
        "passBay": C.spot_id(C.HERO_LEVEL, C.PASS_ROW, C.HERO_COL),
        "route": {k: round(float(v), 3) for k, v in times.items()},  # temps de route d'une voiture (s)
        "loopTimes": {k: round(float(v) % C.LOOP, 3) for k, v in times.items()},  # mêmes instants dans la boucle
        "views": {},
    }
    Z = C.ROOF_Z
    anchors = {
        "hero": {
            "gate": (C.X_IN, C.GATE_IN_Y - 3.0, 3.4),
            "bay": (C.HERO_X, 2.5, Z + 2.4),
            "tower": (C.TOWER[0], C.TOWER[1], Z + 3.4),
            "lift": (-28.4, -14.1, Z + 4.2),
            "ev": (C.spot_x(8), -C.BY - 0.6, 0.6),
            **{f"P{lv}": (-C.BX - 0.3, -C.BY - 0.3, lv * C.LEVEL_H + 1.7) for lv in range(C.NLEV)},
        },
        "gate": {
            "anpr": (C.ISLAND_X, -24.2, 3.25),
            "plate": (C.X_IN, R.Y_STOP - R.TAIL, 0.72),
            "car": (C.X_IN, R.Y_STOP + 1.2, 2.25),
            "barrier": (C.ISLAND_X + 1.9, C.GATE_IN_Y, 1.25),
            "exit": (C.X_OUT, C.GATE_OUT_Y, 2.4),
        },
        "roof": {
            "bay": (C.HERO_X, 2.5, Z + 0.1),
            "bayTop": (C.HERO_X, 2.5, Z + 2.5),
            "pass": (C.HERO_X, -2.5, Z + 0.1),
            "aisle": (14.0, C.Y_A2_WEST, Z + 0.1),
            **{f"bay{i}": p for i, p in enumerate([(C.HERO_X - 1.35, 0.0, Z), (C.HERO_X + 1.35, 0.0, Z), (C.HERO_X + 1.35, 5.0, Z), (C.HERO_X - 1.35, 5.0, Z)])},
        },
    }
    for name in C.VIEWS:
        view = View(name)
        a = {k: [round(v, 1) for v in view.stage(p)] for k, p in anchors[name].items()}
        sync["views"][name] = {"anchors": a, "mPerUnit": round(view.metres_per_unit(), 5)}
    json.dump(sync, open(os.path.join(OUT, "sync.json"), "w"), separators=(",", ":"))
    print("EXPORT", {k: round(v, 2) for k, v in sync["loopTimes"].items()})
    for name in C.VIEWS:
        print(name, sync["views"][name]["anchors"])


if __name__ == "__main__":
    main()
