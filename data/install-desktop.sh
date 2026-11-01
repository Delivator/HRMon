#!/bin/sh
# Install a desktop entry + icon so HRMon shows up in the Plasma app launcher.
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
apps="$HOME/.local/share/applications"
icons="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$apps" "$icons"
cp "$root/data/hrmon.svg" "$icons/io.github.hrmon.HRMon.svg"
cat > "$apps/io.github.hrmon.HRMon.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=HRMon
Comment=Live heart rate from a Bluetooth chest strap
Exec=$root/hrmon.sh
Icon=io.github.hrmon.HRMon
Categories=Utility;
StartupWMClass=io.github.hrmon.HRMon
EOF
echo "Installed $apps/io.github.hrmon.HRMon.desktop"
