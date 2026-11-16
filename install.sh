#!/usr/bin/env bash
# Installs Cert Deck for the current user on Ubuntu/Debian (venv in ~/.local/share/certdeck-app).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PREFIX="$HOME/.local/share/certdeck-app"

echo "==> System dependencies (needs sudo)"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip \
    libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libdbus-1-3 libfontconfig1

echo "==> Virtual environment and package"
python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --upgrade pip
"$PREFIX/venv/bin/pip" install "$HERE"

echo "==> Launcher and icon"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/scalable/apps"
ln -sf "$PREFIX/venv/bin/certdeck" "$HOME/.local/bin/certdeck"
cp "$HERE/packaging/certdeck.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/certdeck.svg"
sed -e "s|@EXEC@|$PREFIX/venv/bin/certdeck|" -e "s|@ICON@|certdeck|" "$HERE/packaging/certdeck.desktop" \
    > "$HOME/.local/share/applications/certdeck.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -q -t -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo "Done. Start 'certdeck' from the applications menu or from a terminal."
