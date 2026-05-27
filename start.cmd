@echo off
REM SYNQ — one-shot dev startup.
REM Brings up docker infra, then opens API, Celery worker, and Next.js
REM in three separate windows so each process's logs stay visible.

setlocal
set "ROOT=%~dp0"

echo [synq] starting docker infra...
docker compose up -d
if errorlevel 1 (
    echo [synq] docker compose failed — aborting.
    exit /b 1
)

echo [synq] launching API on :8000
start "synq-api" cmd /k "cd /d %ROOT%apps\api && .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

echo [synq] launching Celery worker
start "synq-worker" cmd /k "cd /d %ROOT%apps\api && .\.venv\Scripts\python.exe -m celery -A app.workers.celery_app worker --loglevel=info --pool=solo"

echo [synq] launching Next.js on :3000
start "synq-web" cmd /k "cd /d %ROOT% && npm run dev:web"

echo.
echo [synq] up. Open http://localhost:3000
echo [synq] Jaeger UI: http://localhost:16686
echo [synq] Stop everything with: stop.cmd
endlocal
