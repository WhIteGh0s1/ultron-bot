#!/usr/bin/env bash
# Установка Альтрона на чистый Ubuntu-сервер (Oracle Cloud Free, любой VPS).
# Запуск:  curl -fsSL -H "Authorization: token ТВОЙ_GH_ТОКЕН" \
#            https://raw.githubusercontent.com/WhIteGh0s1/ultron-bot/main/deploy/install.sh | sudo -E bash
# или скопируй файл на сервер и:  sudo bash install.sh
set -euo pipefail

REPO="${REPO:-WhIteGh0s1/ultron-bot}"
MEMORY_REPO="${MEMORY_REPO:-WhIteGh0s1/ultron-memory}"
DIR=/opt/altron
DATA=/opt/altron-data

ask() { local v; read -r -p "$1: " v < /dev/tty; echo "$v"; }

GH_TOKEN="${GH_TOKEN:-$(ask 'GitHub токен (доступ к ultron-bot и ultron-memory)')}"
BOT_TOKEN="${BOT_TOKEN:-$(ask 'Токен бота от BotFather')}"
LLM_API_KEY="${LLM_API_KEY:-$(ask 'Ключ Tooken (TOKEN_CLUB_API_KEY)')}"

apt-get update -qq
apt-get install -y -qq git python3 python3-venv python3-pip >/dev/null

if [ ! -d "$DIR/.git" ]; then
  git clone -q "https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git" "$DIR"
fi
cd "$DIR"
git pull -q --ff-only || true
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

mkdir -p "$DATA"
if [ ! -f .env ]; then
  cp .env.example .env
  sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=${BOT_TOKEN}|; s|^LLM_API_KEY=.*|LLM_API_KEY=${LLM_API_KEY}|; \
s|^DATA_DIR=.*|DATA_DIR=${DATA}|; s|^MEMORY_REPO=.*|MEMORY_REPO=${MEMORY_REPO}|; \
s|^GH_TOKEN=.*|GH_TOKEN=${GH_TOKEN}|; s|^AUTO_UPDATE=.*|AUTO_UPDATE=1|" .env
  chmod 600 .env
fi

cat > /etc/systemd/system/altron.service <<UNIT
[Unit]
Description=Altron Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=${DIR}
ExecStart=${DIR}/.venv/bin/python -X utf8 bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now altron
sleep 5
systemctl --no-pager status altron | head -n 5
echo
echo "Готово. Логи: journalctl -u altron -f"
echo "Бот сам перезапускается при падении и сам подтягивает новый код из GitHub каждые 10 минут."
