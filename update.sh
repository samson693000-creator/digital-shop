#!/usr/bin/env bash
# Быстрый апдейт уже установленного Digital Shop
set -euo pipefail
INSTALL_DIR="${INSTALL_DIR:-/opt/digital-shop}"
SERVICE_NAME="digital-shop"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Нужен root: sudo bash update.sh"
  exit 1
fi

cd "$INSTALL_DIR"
git pull --ff-only
.venv/bin/pip install -r requirements.txt
systemctl restart "$SERVICE_NAME"
systemctl --no-pager --full status "$SERVICE_NAME" | head -n 20
echo "Обновлено."
