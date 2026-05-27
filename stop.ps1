# SYNQ — one-shot dev shutdown.
# Kills the three dev processes started by start.ps1 and stops docker infra.

$ErrorActionPreference = "Continue"

Write-Host "[synq] stopping uvicorn + celery + next..." -ForegroundColor Cyan

# Match by command-line so we only kill the synq dev processes, not any
# other python / node on the box.
$patterns = @(
    'uvicorn app.main:app',
    'celery -A app.workers.celery_app',
    'next dev',
    'npm run dev:web',
    'npm exec next'
)

foreach ($pat in $patterns) {
    $procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$pat*" }
    foreach ($p in $procs) {
        Write-Host "  killing pid $($p.ProcessId) — $pat"
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "[synq] stopping docker infra..." -ForegroundColor Cyan
docker compose -f "$PSScriptRoot\docker-compose.yml" down

Write-Host "[synq] all stopped." -ForegroundColor Green
