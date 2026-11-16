"""
Exporte vers le site les données calculées avec la scène 3D :
  src/data/layout.json : les 240 places (type, état initial, plaque) et les places
                         verrouillées (celles que la vidéo anime : la simulation du site n'y touche pas)
  src/data/sync.json   : boucle, passages aux barrières (plaque lue, ouverture, fermeture),
                         occupation des places de la flotte, instants de la voiture suivie, et
                         ancrages des étiquettes par vue (coordonnées de la maquette 1280 x 776).

  blender -b --factory-startup -P blender/export_data.py
"""

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import actors  # noqa: E402
import config as C  # noqa: E402
import fleet as F  # noqa: E402
import layout  # noqa: E402
import traffic  # noqa: E402
from camera import View  # noqa: E402
from carspecs import STYLES  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "src", "data")
r3 = lambda v: round(float(v) % C.LOOP, 3)


def main():
    os.makedirs(OUT, exist_ok=True)
    fleet = traffic.plan()
    ins, outs = actors.gate_events(fleet)
    bays = actors.bay_events(fleet)
    spots = layout.make()
    hero_spot = next(s for s in spots if s["hero"])
    locked = sorted(C.spot_id(*k) for k in set(F.bays()) | F.clear_bays())
    keep = ("id", "level", "row", "col", "type", "status", "plate", "style", "paint", "hero")
    json.dump(
        {"levels": C.NLEV, "rows": C.NROW, "cols": C.NCOL, "rate": 3.5, "paints": [p[1] for p in C.PAINTS], "accent": C.ACCENT, "locked": locked, "spots": [{k: s[k] for k in keep} for s in spots]},
        open(os.path.join(OUT, "layout.json"), "w"),
        separators=(",", ":"),
    )

    hero = fleet.by_name["hero"]
    hb = bays[hero.bay]
    gate_view = View("gate")
    entries = []
    for e in ins:
        c = fleet.by_name[e["chain"]]
        tau = c.trip.events["gate"] + 0.35 if e["stop"] is not None else c.trip.events["anpr"] + 0.1
        st = c.trip.sample(tau)
        x, y, psi = float(st["x"]), float(st["y"]), float(st["psi"])
        plate = (x - c.d.tail * math.cos(psi), y - c.d.tail * math.sin(psi), STYLES[c.style]["plate"]["rear"] * C.CAR_SCALE)
        entries.append({"plate": e["plate"], "t": r3(e["flash"]), "stop": None if e["stop"] is None else r3(e["stop"]), "open": r3(e["open"]), "close": r3(e["close"]), "at": [round(v, 1) for v in gate_view.stage(plate)], "hero": c.name == "hero"})
    sync = {
        "fps": C.FPS,
        "loop": C.LOOP,
        "frames": C.FRAMES,
        "chains": len(fleet.chains),
        "vehicles": len(fleet.cars()),
        "plate": hero_spot["plate"],
        "bay": hero_spot["id"],
        "passBay": C.spot_id(C.HERO_LEVEL, C.PASS_ROW, C.HERO_COL),
        # instants de la voiture suivie, dans la boucle
        "hero": {"flash": r3(hero.at("gate") + 0.35), "stop": r3(hero.at("gate")), "roof": r3(hero.at("roof")), "reserved": r3(hb["reserved"]), "parked": r3(hb["on"]), "leave": r3(hero.at("parked_end")), "clear": r3(hb["off"])},
        "entries": entries,
        "exits": [{"plate": e["plate"], "open": r3(e["open"]), "gate": r3(e["gate"]), "close": r3(e["close"])} for e in outs],
        # places animées par la vidéo : occupées de « on » à « off »
        "bays": [{"id": C.spot_id(*k), "on": r3(e["on"]), "off": r3(e["off"]), **({"reserved": r3(e["reserved"])} if "reserved" in e else {})} for k, e in sorted(bays.items())],
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
    sync["views"]["gate"]["anchors"]["plate"] = next(e["at"] for e in entries if e["hero"])
    json.dump(sync, open(os.path.join(OUT, "sync.json"), "w"), separators=(",", ":"))
    print("EXPORT boucle", C.LOOP, "s ;", len(entries), "entrées,", len(sync["exits"]), "sorties,", len(sync["bays"]), "places animées")
    print("  voiture suivie :", sync["hero"])
    for e in entries:
        print("  entrée", e)


if __name__ == "__main__":
    main()
