# SYNQ — one-shot dev startup.
# Brings up docker infra, then launches API, Celery worker, and Next.js
# in three separate PowerShell windows so each process's logs stay visible.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "[synq] starting docker infra..." -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "[synq] docker compose failed — aborting." -ForegroundColor Red
    exit 1
}

Write-Host "[synq] launching API on :8000" -ForegroundColor Cyan
Start-Process powershell -ArgumentList '-NoExit','-Command',"cd '$root\apps\api'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

Write-Host "[synq] launching Celery worker" -ForegroundColor Cyan
Start-Process powershell -ArgumentList '-NoExit','-Command',"cd '$root\apps\api'; .\.venv\Scripts\python.exe -m celery -A app.workers.celery_app worker --loglevel=info --pool=solo"

Write-Host "[synq] launching Next.js on :3000" -ForegroundColor Cyan
Start-Process powershell -ArgumentList '-NoExit','-Command',"cd '$root'; npm run dev:web"

Write-Host ""
Write-Host "[synq] up. Open http://localhost:3000" -ForegroundColor Green
Write-Host "[synq] Jaeger UI: http://localhost:16686"
Write-Host "[synq] Stop everything with: .\stop.ps1"
