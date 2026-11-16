"""
La flotte en circulation (données pures) : qui roule, avec quel véhicule, où il va,
comment il conduit et quand il entre dans la boucle.

Chaque ligne est une « chaîne » : un trajet rejoué toutes les LOOP secondes. Si le
trajet dure plus d'une boucle, plusieurs véhicules identiques s'y succèdent (taxis,
voitures bleues en libre-service, voitures de couleur courante) ; les véhicules
très reconnaissables n'apparaissent qu'une fois : ils viennent de l'extérieur et
disparaissent dans un niveau couvert, ou l'inverse.

Trajets (traffic.py) :
  roof   : route -> barrière -> rampe -> toit -> place (row, col) -> attente -> sortie
  loop   : taxi : tour du toit, dépose, sortie
  p2_in  : route -> barrière -> rampe -> niveau P2 (disparaît dans l'allée couverte)
  p2_out : sort du niveau P2 -> rampe -> barrière de sortie -> route
  visit  : niveau couvert : arrive de l'allée, se gare en façade sud, repart
Ordre de la liste = ordre de priorité : chaque chaîne s'adapte à celles qui la précèdent
(elle les suit, leur cède le passage, attend la fin de leur manœuvre). On place donc d'abord
ceux qui s'insèrent ou manœuvrent, et les conducteurs lents avant les rapides.
"""

import config as C

# niveau, rangée (0 = A … 3 = D), colonne
HERO = (C.HERO_LEVEL, C.HERO_ROW, C.HERO_COL)

def _c(name, style, paint, plate, drv, t0, trip, gate=None, **args):
    return {"name": name, "style": style, "paint": paint, "plate": plate, "drv": drv, "t0": t0, "trip": trip, "gate": gate, "args": args}


FLEET = [
    # --- départs du niveau P2 : ils coupent la voie montante et s'insèrent dans la descente
    _c("berline_bordeaux", "sedan", "#7a2338", "BX-427-EV", "calme", 14.0, "p2_out"),
    _c("turquoise", "hatch", "#19a7b8", "TQ-857-FA", "normal", 3.0, "p2_out"),
    _c("mini_corail", "mini", "#e2532f", "MC-266-UR", "normal", 39.0, "p2_out"),
    _c("citadine_ciel", "hatch", "#58a8e0", "CL-059-JW", "vif", 27.0, "p2_out"),
    # --- toit : particuliers, taxis, voitures bleues en libre-service (la place suivie par le site)
    _c("citadine", "hatch", 0, "GH-518-LM", "calme", 12.0, "roof", "stop", row=1, col=3, enter="swing", leave="back90", dwell=12.0),
    _c("taxi", "taxi", "#f2c230", "TX-204-PK", "vif", 18.0, "loop", "pass", stop_x=-12.0, hold=4.5),
    _c("berline", "sedan", 2, "DK-771-RS", "normal", 30.0, "roof", "pass", row=3, col=5, enter="swing", leave="back65", dwell=10.0),
    _c("hero", "mini", "hero", "AB-123-CD", "normal", 0.0, "roof", "stop", row=C.HERO_ROW, col=C.HERO_COL, enter="left", leave="through", dwell=15.0),
    # --- arrivées au niveau P2 (elles disparaissent sous la dalle)
    _c("fourgon", "van", "#f1f2f4", "LV-336-TB", "calme", 24.0, "p2_in", "stop"),
    _c("suv_vert", "suv", "#2f8f63", "SV-640-NC", "normal", 36.0, "p2_in", "pass"),
    _c("pickup_orange", "pickup", "#e8762c", "PU-185-HD", "normal", 42.0, "p2_in", "stop"),
    _c("coupe_rouge", "coupe", "#cf3b33", "FR-902-ZA", "vif", 6.0, "p2_in", "pass"),
    # --- niveaux couverts : stationnements en façade sud
    _c("v_mini_menthe", "mini", "#3fb6a0", "MN-310-QA", "normal", 1.0, "visit", level=2, col=7, dwell=15.0),
    _c("v_suv_noir", "suv", 4, "NR-864-PD", "calme", 22.0, "visit", level=2, col=10, dwell=9.0),
    _c("v_sedan_marine", "sedan", 9, "MR-630-DC", "normal", 38.5, "visit", level=2, col=1, dwell=12.0),
    _c("v_coupe_jaune", "coupe", "#e9b93a", "JN-572-KX", "vif", 11.5, "visit", level=1, col=4, dwell=12.0),
    _c("v_van_bleu", "van", "#3d6fd1", "VB-218-GS", "calme", 27.5, "visit", level=1, col=8, dwell=10.0),
    _c("v_hatch_rouge", "hatch", "#c8452f", "RG-093-MT", "normal", 17.0, "visit", level=1, col=11, dwell=14.0),
    _c("v_pickup_gris", "pickup", 3, "GP-745-BL", "normal", 33.0, "visit", level=0, col=7, dwell=11.0),
    _c("v_sedan_violet", "sedan", "#6a4bb0", "VT-401-YH", "calme", 6.5, "visit", level=0, col=10, dwell=16.0),
    _c("v_suv_sable", "suv", 5, "SB-912-WN", "normal", 44.0, "visit", level=0, col=5, dwell=10.0),
]


def bays():
    """Places utilisées par la flotte : {(niveau, rangée, colonne): nom de la chaîne}."""
    out = {}
    for f in FLEET:
        a = f["args"]
        if f["trip"] == "roof":
            out[(C.HERO_LEVEL, a["row"], a["col"])] = f["name"]
        elif f["trip"] == "visit":
            out[(a["level"], 0, a["col"])] = f["name"]
    return out


def clear_bays():
    """Places qui doivent rester vides : traversée de la voiture bleue, dégagement des virages
    d'entrée (côté extérieur du virage) et des demi-tours du toit."""
    out = {(C.HERO_LEVEL, C.PASS_ROW, C.HERO_COL), (C.HERO_LEVEL, 0, 0), (C.HERO_LEVEL, 3, C.NCOL - 1), (C.HERO_LEVEL, 3, C.NCOL - 2)}
    for (lv, row, col) in bays():
        if col > 0:
            out.add((lv, row, col - 1))
    return out - set(bays())
