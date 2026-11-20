# Один раз: переносит Альтрона жить в GitHub Actions (комп можно выключать).
# Запуск в PowerShell из папки бота:  .\tools\setup_github.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$repo = "WhIteGh0s1/ultron-bot"
$memory = "WhIteGh0s1/ultron-memory"

function EnvValue($name) {
    $line = Get-Content .env -Encoding UTF8 | Where-Object { $_ -match "^$name=" } | Select-Object -First 1
    if (-not $line) { throw "в .env нет $name" }
    return ($line -replace "^$name=", "").Trim()
}

Write-Host "1/5 ключ, которым Actions пишет в приватную память" -ForegroundColor Cyan
$key = Join-Path $env:TEMP ("altron_key_" + (Get-Random))
Start-Process ssh-keygen -ArgumentList "-q -t ed25519 -N `"`" -C altron-actions -f `"$key`"" -NoNewWindow -Wait
gh repo deploy-key add "$key.pub" -R $memory --allow-write -t "altron-actions"
Get-Content $key -Raw | gh secret set MEMORY_DEPLOY_KEY -R $repo
Remove-Item "$key", "$key.pub" -Force

Write-Host "2/5 токен бота, id старосты, ключ Tooken -> секреты репозитория" -ForegroundColor Cyan
gh secret set BOT_TOKEN -R $repo --body (EnvValue "BOT_TOKEN")
gh secret set OWNER_IDS -R $repo --body (EnvValue "OWNER_IDS")
$llm = [Environment]::GetEnvironmentVariable("TOKEN_CLUB_API_KEY", "User")
if (-not $llm) { throw "нет переменной TOKEN_CLUB_API_KEY" }
gh secret set LLM_API_KEY -R $repo --body $llm

Write-Host "3/5 репозиторий публичный (у публичных Actions бесплатны без лимита, память остаётся приватной)" -ForegroundColor Cyan
gh repo edit $repo --visibility public --accept-visibility-change-consequences

Write-Host "4/5 выключаю бота на этом компьютере (двоим нельзя)" -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*bot.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Write-Host "5/5 запускаю в GitHub Actions" -ForegroundColor Cyan
gh workflow enable bot.yml -R $repo
gh workflow run bot.yml -R $repo
Write-Host ""
Write-Host "Готово. Через минуту бот поднимется в GitHub. Смотреть: https://github.com/$repo/actions" -ForegroundColor Green
