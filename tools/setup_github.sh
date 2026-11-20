#!/usr/bin/env bash
# Один раз: переносит Альтрона жить в GitHub Actions.
# Запуск из папки бота:  bash tools/setup_github.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=WhIteGh0s1/ultron-bot
MEMORY=WhIteGh0s1/ultron-memory

echo "1/5 ключ, которым Actions пишет в приватную память"
K="$(mktemp -u)"
ssh-keygen -q -t ed25519 -N "" -C altron-actions -f "$K"
gh repo deploy-key add "$K.pub" -R "$MEMORY" --allow-write -t altron-actions
gh secret set MEMORY_DEPLOY_KEY -R "$REPO" < "$K"
rm -f "$K" "$K.pub"

echo "2/5 токен бота, id старосты, ключ Tooken → секреты репозитория"
grep '^BOT_TOKEN=' .env | cut -d= -f2- | tr -d '\r\n' | gh secret set BOT_TOKEN -R "$REPO"
grep '^OWNER_IDS=' .env | cut -d= -f2- | tr -d '\r\n' | gh secret set OWNER_IDS -R "$REPO"
powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('TOKEN_CLUB_API_KEY','User')" \
  | tr -d '\r\n' | gh secret set LLM_API_KEY -R "$REPO"

echo "3/5 репозиторий публичный — у публичных Actions бесплатны без лимита (память остаётся приватной)"
gh repo edit "$REPO" --visibility public --accept-visibility-change-consequences

echo "4/5 выключаю бота на этом компьютере (двоим нельзя)"
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*bot.py*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" || true

echo "5/5 запускаю в Actions"
gh workflow enable bot.yml -R "$REPO"
gh workflow run bot.yml -R "$REPO"
echo
echo "Готово. Смотреть: https://github.com/$REPO/actions"
