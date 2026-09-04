#!/usr/bin/env bash
# Digital Shop — one-command installer (bot + web admin)
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/OWNER/REPO/main/install.sh | sudo bash
# Or with options:
#   curl -fsSL ... | sudo bash -s -- --dir /opt/digital-shop --port 8000

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/samson693000-creator/digital-shop.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-/opt/digital-shop}"
APP_USER="${APP_USER:-digishop}"
APP_PORT="${APP_PORT:-8000}"
SERVICE_NAME="digital-shop"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[digital-shop]${NC} $*"; }
ok()   { echo -e "${GREEN}[ok]${NC} $*"; }
err()  { echo -e "${RED}[error]${NC} $*"; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)   INSTALL_DIR="$2"; shift 2 ;;
    --port)  APP_PORT="$2"; shift 2 ;;
    --user)  APP_USER="$2"; shift 2 ;;
    --repo)  REPO_URL="$2"; shift 2 ;;
    --branch) REPO_BRANCH="$2"; shift 2 ;;
    *) err "Unknown option: $1" ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  err "Запустите от root: curl ... | sudo bash"
fi

log "Установка Digital Shop → ${INSTALL_DIR}"
log "Порт админки: ${APP_PORT}"

export DEBIAN_FRONTEND=noninteractive

if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y python3 python3-venv python3-pip git curl ca-certificates
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y python3 python3-pip git curl ca-certificates
elif command -v yum >/dev/null 2>&1; then
  yum install -y python3 python3-pip git curl ca-certificates
else
  err "Нужен apt/dnf/yum (Ubuntu/Debian/CentOS/Fedora)"
fi

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$APP_USER" || true
fi

if [[ -d "$INSTALL_DIR/.git" ]]; then
  log "Обновление репозитория..."
  git -c "safe.directory=${INSTALL_DIR}" -C "$INSTALL_DIR" fetch --depth 1 origin "$REPO_BRANCH"
  git -c "safe.directory=${INSTALL_DIR}" -C "$INSTALL_DIR" reset --hard "origin/$REPO_BRANCH"
else
  log "Клонирование ${REPO_URL}..."
  rm -rf "$INSTALL_DIR"
  git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

log "Создание venv и установка зависимостей..."
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

SECRET="$(openssl rand -hex 24 2>/dev/null || head -c 48 /dev/urandom | xxd -p -c 48)"
ADMIN_PASS="$(openssl rand -hex 8 2>/dev/null || head -c 16 /dev/urandom | xxd -p -c 16)"

if [[ ! -f .env ]]; then
  cp .env.example .env
  sed -i "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=${ADMIN_PASS}|" .env
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env
  sed -i "s|^HOST=.*|HOST=0.0.0.0|" .env
  sed -i "s|^PORT=.*|PORT=${APP_PORT}|" .env
  CREATED_ENV=1
else
  CREATED_ENV=0
  # keep existing secrets; only sync port if empty
  grep -q "^PORT=" .env || echo "PORT=${APP_PORT}" >> .env
  ADMIN_PASS="$(grep '^ADMIN_PASSWORD=' .env | cut -d= -f2-)"
fi

mkdir -p data
chown -R "$APP_USER:$APP_USER" "$INSTALL_DIR"

log "Настройка systemd..."
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Digital Shop (Telegram bot + Web admin)
After=network.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/.venv/bin/python ${INSTALL_DIR}/main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

sleep 2
if systemctl is-active --quiet "${SERVICE_NAME}"; then
  ok "Сервис ${SERVICE_NAME} запущен"
else
  err "Сервис не стартовал. Смотрите: journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
fi

IP="$(curl -fsSL ifconfig.me 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo 'SERVER_IP')"

echo
ok "Установка завершена"
echo "────────────────────────────────────────────"
echo "  Админка:  http://${IP}:${APP_PORT}"
echo "  Логин:    admin"
if [[ "$CREATED_ENV" -eq 1 ]]; then
  echo "  Пароль:   ${ADMIN_PASS}"
else
  echo "  Пароль:   (из ${INSTALL_DIR}/.env)"
fi
echo "  Каталог:  ${INSTALL_DIR}"
echo "  Сервис:   systemctl status ${SERVICE_NAME}"
echo "────────────────────────────────────────────"
echo
echo "Дальше:"
echo "  1) Откройте админку → Настройки → вставьте BOT_TOKEN"
echo "  2) systemctl restart ${SERVICE_NAME}"
echo "  3) (опционально) nginx + HTTPS перед портом ${APP_PORT}"
echo
