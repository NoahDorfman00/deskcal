#!/bin/sh
# Export every printable part of the stand to stl/, already oriented for the bed.
# Needs an OpenSCAD with the Manifold backend (2024 or newer).
set -e
cd "$(dirname "$0")"
mkdir -p stl
for part in body back handle knob_big knob_small clip bnc lock fit_test; do
    echo "exporting $part"
    openscad --backend=Manifold --export-format binstl -D "part=\"$part\"" -o "stl/$part.stl" deskcal_stand.scad
done
