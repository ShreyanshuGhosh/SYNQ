@echo off
REM SYNQ — one-shot dev shutdown.
REM Closes the three dev windows by title, then stops docker infra.

echo [synq] stopping API window...
taskkill /FI "WINDOWTITLE eq synq-api*" /T /F >nul 2>&1

echo [synq] stopping Celery window...
taskkill /FI "WINDOWTITLE eq synq-worker*" /T /F >nul 2>&1

echo [synq] stopping Next.js window...
taskkill /FI "WINDOWTITLE eq synq-web*" /T /F >nul 2>&1

echo [synq] stopping docker infra...
docker compose -f "%~dp0docker-compose.yml" down

echo [synq] all stopped.
