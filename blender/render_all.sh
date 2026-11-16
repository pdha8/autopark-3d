#!/bin/bash
# Rend puis encode les vidéos d'AutoPark 3D (fond fixe + zones animées).
# Usage : bash blender/render_all.sh [variantes]   ex. hero_night hero_day gate_night
# Variantes : hero_day hero_night gate_day gate_night roof_day roof_night
# L'assemblage d'une vidéo (processeur) se fait pendant le rendu de la suivante (carte graphique).
# Les zones rendues (plus de 10 Go par vidéo) sont supprimées une fois la vidéo encodée et
# vérifiée ; KEEP_ZONES=1 les conserve. Un rendu interrompu reprend là où il s'est arrêté.
# LEVELS=1 refait d'abord les plans des niveaux de l'explorateur (carte graphique, ~10 min).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BLENDER="${BLENDER:-/c/Program Files/Blender Foundation/Blender 5.2/blender.exe}"
VARIANTS="${*:-hero_night hero_day gate_night gate_day roof_night roof_day}"
PURGE="--purge"; [ "${KEEP_ZONES:-0}" = "1" ] && PURGE=""
mkdir -p "$ROOT/blender/work" "$ROOT/public/video"

compose() {
  local v="$1" log="$ROOT/blender/work/render_$1.log"
  "$BLENDER" -b --factory-startup -P "$ROOT/blender/compose.py" -- --name "$v" $PURGE >> "$log" 2>&1
  echo "=== $v : vidéo prête ($(date +%H:%M:%S))"
  grep -E "VIDEO|ZONES (supprimées|conservées)|Traceback|Error" "$log" | tail -3
}

if [ "${LEVELS:-0}" = "1" ]; then
  echo "=== plans des niveaux ($(date +%H:%M:%S))"
  "$BLENDER" -b --factory-startup -P "$ROOT/blender/levels.py" -- --gpu > "$ROOT/blender/work/levels.log" 2>&1
  grep -E "NIVEAU|TERMINE|Traceback|Error" "$ROOT/blender/work/levels.log" | tail -3
fi

for v in $VARIANTS; do
  view="${v%%_*}"; mode="${v#*_}"
  night=""; [ "$mode" = "night" ] && night="--night"
  log="$ROOT/blender/work/render_$v.log"
  echo "=== $v : rendu ($(date +%H:%M:%S))"
  "$BLENDER" -b --factory-startup -P "$ROOT/blender/render.py" -- --view "$view" $night --anim > "$log" 2>&1
  grep -E "FOND|ZONES|Traceback|Error" "$log" | tail -3
  wait  # l'assemblage de la vidéo précédente doit être terminé
  compose "$v" &
done
wait
echo "=== TERMINE ($(date +%H:%M:%S))"
