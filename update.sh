#!/usr/bin/env bash
# Быстрый апдейт уже установленного Digital Shop
#   curl -fsSL https://raw.githubusercontent.com/samson693000-creator/digital-shop/main/update.sh | sudo bash
set -euo pipefail
INSTALL_DIR="${INSTALL_DIR:-/opt/digital-shop}"
SERVICE_NAME="digital-shop"
APP_USER="${APP_USER:-digishop}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Нужен root: sudo bash update.sh"
  exit 1
fi

cd "$INSTALL_DIR"

# root обновляет репо, которым владеет digishop — без safe.directory git ругается
git -c "safe.directory=${INSTALL_DIR}" fetch --depth 1 origin main
git -c "safe.directory=${INSTALL_DIR}" reset --hard origin/main

.venv/bin/pip install -r requirements.txt
chown -R "${APP_USER}:${APP_USER}" "$INSTALL_DIR"
systemctl restart "$SERVICE_NAME"
systemctl --no-pager --full status "$SERVICE_NAME" | head -n 20
echo "Обновлено."
