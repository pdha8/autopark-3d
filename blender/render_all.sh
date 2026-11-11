#!/bin/bash
# Rend puis encode les vidéos d'AutoPark 3D (fond fixe + zones animées).
# Usage : bash blender/render_all.sh [variantes]   ex. hero_night hero_day gate_night
# Variantes : hero_day hero_night gate_day gate_night roof_day roof_night
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BLENDER="${BLENDER:-/c/Program Files/Blender Foundation/Blender 5.2/blender.exe}"
VARIANTS="${*:-hero_night hero_day gate_night gate_day roof_night roof_day}"
mkdir -p "$ROOT/blender/work" "$ROOT/public/video"
for v in $VARIANTS; do
  view="${v%%_*}"; mode="${v#*_}"
  night=""; [ "$mode" = "night" ] && night="--night"
  log="$ROOT/blender/work/render_$v.log"
  echo "=== $v : rendu ($(date +%H:%M:%S))"
  "$BLENDER" -b --factory-startup -P "$ROOT/blender/render.py" -- --view "$view" $night --anim > "$log" 2>&1
  grep -E "FOND|ZONES|Traceback|Error" "$log" | tail -4
  echo "=== $v : assemblage et encodage ($(date +%H:%M:%S))"
  "$BLENDER" -b --factory-startup -P "$ROOT/blender/compose.py" -- --name "$v" >> "$log" 2>&1
  grep -E "VIDEO|TERMINE|Traceback|Error" "$log" | tail -3
done
echo "=== TERMINE ($(date +%H:%M:%S))"
