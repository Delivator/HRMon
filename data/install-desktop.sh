#!/bin/sh
# Install a desktop entry + icon so HRMon shows up in the Plasma app launcher.
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
apps="$HOME/.local/share/applications"
icons="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$apps" "$icons"
cp "$root/data/hrmon.svg" "$icons/io.github.Delivator.HRMon.svg"
cat > "$apps/io.github.Delivator.HRMon.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=HRMon
Comment=Live heart rate from a Bluetooth chest strap
Exec=$root/hrmon.sh
Icon=io.github.Delivator.HRMon
Categories=Utility;
StartupWMClass=io.github.Delivator.HRMon
EOF
echo "Installed $apps/io.github.Delivator.HRMon.desktop"
