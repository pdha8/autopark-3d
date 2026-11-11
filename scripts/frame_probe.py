"""Sonde de cadrage : où tombent les points clés de la scène dans la maquette 1280 x 776."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender"))
import config as C
from camera import View

def probe(name, spec=None):
    v = View(name, spec)
    Z = C.ROOF_Z
    pts = {
        "toit SO": (-C.BX, -C.BY, Z), "toit SE": (C.BX, -C.BY, Z), "toit NE": (C.BX, C.BY, Z), "toit NO": (-C.BX, C.BY, Z),
        "sol SO": (-C.BX, -C.BY, 0), "sol SE": (C.BX, -C.BY, 0),
        "tour haut": (C.TOWER[0], C.TOWER[1], Z + 1.5), "tour E sol": (C.TOWER[0] + C.R_OUT, C.TOWER[1], 0), "tour S sol": (C.TOWER[0], C.TOWER[1] - C.R_OUT, 0),
        "barriere": (C.ISLAND_X, C.GATE_IN_Y, 0), "place heros": (C.HERO_X, 2.5, Z),
        "socle SO": (C.BASE[0], C.BASE[2], 0), "socle SE": (C.BASE[1], C.BASE[2], 0), "socle NE": (C.BASE[1], C.BASE[3], 0), "socle NO": (C.BASE[0], C.BASE[3], 0),
    }
    print(f"--- {name} : {v.metres_per_unit()*1000:.1f} mm/unité ; voiture de 3,8 m = {3.8/v.metres_per_unit():.0f} u = {3.8/v.metres_per_unit()*1.5:.0f} px")
    for k, p in pts.items():
        x, y = v.stage(p)
        print(f"  {k:12s} x={x:7.1f} y={y:7.1f}")
    # où la route sort du cadre complet (bas ou côté)
    for y in range(-30, -200, -1):
        u, vv, _ = v.project((C.ISLAND_X, y, 0))
        if vv < 0 or u < 0 or u > 1:
            print(f"  la route sort du cadre vers y = {y} (u={u:.2f}, v={vv:.2f})")
            break
    return v

if __name__ == "__main__":
    for n in sys.argv[1:] or ["hero"]:
        probe(n)
