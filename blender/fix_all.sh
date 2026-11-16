#!/bin/bash
# Compléments de zones des vidéos publiées, à lancer après render_all.sh avec KEEP_ZONES=1.
# Les rectangles (pixels de l'image finale, origine en haut à gauche) sont les endroits où la
# lumière des voitures dépasse leurs zones ; ils ont été repérés avec scripts/check_steps.py.
# Suffixe @a-b,c-d : seulement sur ces images (entrée de jour : images où une lisse est levée,
# alors que le fond la montre baissée ; à recalculer si la circulation change).
# Chaque vidéo est ensuite assemblée de nouveau.
# Usage : bash blender/fix_all.sh [variantes]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BLENDER="${BLENDER:-/c/Program Files/Blender Foundation/Blender 5.2/blender.exe}"
VARIANTS="${*:-gate_day gate_night roof_day roof_night hero_night}"
rects() {
  case "$1" in
    gate_day) echo "--rect 840,120,1176,640 --rect 696,0,1320,192 --rect 1271,456,1709,686@24-328,508-782,979-1650,1718-2293,2585-2839 --rect 1485,536,1932,770@0-371,619-888,1018-1544,1552-2061,2221-2524,2778-2879" ;;
    gate_night) echo "--rect 840,120,1176,640 --rect 696,0,1320,192 --rect 1656,0,2200,240 --rect 984,1032,1752,1200" ;;
    roof_day) echo "--rect 0,552,264,792 --rect 840,312,1176,648" ;;
    roof_night) echo "--rect 0,552,264,792 --rect 840,312,1176,648 --rect 720,96,1344,288 --rect 384,0,576,120" ;;
    hero_night) echo "--rect 720,456,1056,744 --rect 1296,1248,1632,1440" ;;
  esac
}
cd "$ROOT" || exit 1
for v in $VARIANTS; do
  view="${v%%_*}"; mode="${v#*_}"
  night=""; [ "$mode" = "night" ] && night="--night"
  r="$(rects "$v")"
  [ -n "$r" ] || { echo "=== $v : aucun complément prévu"; continue; }
  echo "=== $v : compléments de zones ($(date +%H:%M:%S))"
  if [ "$v" = "roof_night" ]; then  # premier morceau : grain du fond (voir rerender_zones.py)
    "$BLENDER" -b --factory-startup --python-exit-code 1 -P blender/rerender_zones.py -- --view "$view" $night --frames 0-239 > "blender/work/rerender_$v.log" 2>&1 || { echo "=== $v : échec (blender/work/rerender_$v.log)"; continue; }
  fi
  "$BLENDER" -b --factory-startup --python-exit-code 1 -P blender/fix_zones.py -- --view "$view" $night $r > "blender/work/fix_$v.log" 2>&1 || { echo "=== $v : échec (blender/work/fix_$v.log)"; continue; }
  grep -E "^(TOTAL|FIX)" "blender/work/fix_$v.log" | tail -2
  "$BLENDER" -b --factory-startup -P blender/compose.py -- --name "$v" >> "blender/work/render_$v.log" 2>&1
  echo "=== $v : vidéo assemblée ($(date +%H:%M:%S))"
done
