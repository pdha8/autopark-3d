#!/bin/bash
# Versions téléphone des vidéos (*_m.mp4 et *_m.jpg) : sur un téléphone debout, seule une bande
# verticale de chaque vidéo est visible. On ne garde que cette bande (marge comprise), à pleine
# résolution, un peu plus compressée : environ trois fois plus léger, aussi net à l'écran.
# Les bandes doivent rester celles de PHONE_CROP (src/ui/videoScene.js), calculées depuis
# MOBILE_FOCUS (src/main.js). À relancer après chaque nouveau rendu des vidéos.
# Usage : bash scripts/phone_videos.sh
set -eu
cd "$(dirname "$0")/../public/video"
# vue : début de la bande, largeur, hauteur (pixels de la vidéo complète)
crop() {
  case "$1" in
    hero) echo "752 1496 1440" ;;
    gate) echo "1170 784 1200" ;;
    roof) echo "918 840 1200" ;;
  esac
}
for view in hero gate roof; do
  read -r x w h <<< "$(crop "$view")"
  for light in day night; do
    src="${view}_${light}"
    ffmpeg -v error -y -i "$src.mp4" -vf "crop=$w:$h:$x:0" \
      -c:v libx264 -preset slow -crf 26 -profile:v high -g 120 -bf 2 -pix_fmt yuv420p \
      -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv \
      -movflags +faststart -an "${src}_m.mp4"
    ffmpeg -v error -y -i "$src.jpg" -vf "crop=$w:$h:$x:0" -q:v 4 "${src}_m.jpg"
    echo "$src : $(du -h "$src.mp4" | cut -f1) -> $(du -h "${src}_m.mp4" | cut -f1)"
  done
done
