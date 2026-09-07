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

# Кнопка рестарта в админке → systemctl
cat > "/etc/sudoers.d/${SERVICE_NAME}" <<EOF
${APP_USER} ALL=(root) NOPASSWD: /bin/systemctl restart ${SERVICE_NAME}, /bin/systemctl status ${SERVICE_NAME}, /bin/systemctl is-active ${SERVICE_NAME}
EOF
chmod 440 "/etc/sudoers.d/${SERVICE_NAME}"

# Обновим unit, если ставили старый
if [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
  if ! grep -q "KillMode=control-group" "/etc/systemd/system/${SERVICE_NAME}.service"; then
    sed -i '/RestartSec=/a KillMode=control-group\nTimeoutStopSec=15' "/etc/systemd/system/${SERVICE_NAME}.service" || true
    systemctl daemon-reload
  fi
fi

systemctl restart "$SERVICE_NAME"
systemctl --no-pager --full status "$SERVICE_NAME" | head -n 20
echo "Обновлено."
