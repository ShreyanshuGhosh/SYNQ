# Phase 5 Chaos Test Runbook

Verifies the Phase 5 retry/fallback/circuit-breaker pipeline end-to-end.

## What it checks (Phase 5 spec, adapted to free-tier providers)

1. The preferred provider in `FALLBACK_CHAIN` "fails" (synthetic 429).
2. The `provider_switched` SSE event is emitted before the next provider's
   first token.
3. The successful response comes from the next provider in the chain.
4. `usage_events` row has `was_fallback=true` and the correct
   `fallback_from`.
5. Redis key `circuit:<provider>` exists with failure timestamps.
6. After 65 seconds the degraded marker auto-expires (TTL).
7. A subsequent turn routes back to the preferred provider.

## Why we don't revoke a real API key

The spec asks for revoking the upstream provider's key. We can't safely
do that from inside the test harness (the `.env` isn't writable from
Python, and rotating keys mid-test fights with the user's day-to-day
work). Instead the chaos script monkey-patches the preferred adapter's
`stream_completion` to raise a synthetic 429 — observably equivalent
from the orchestrator's point of view.

If you DO want to test true key revocation:
- Comment out `GEMINI_API_KEY` in `apps/api/.env`
- Restart the API + Celery worker
- Send a message via the UI
- Watch the SSE stream emit `provider_switched`
- Restore the key, restart, confirm next message uses Gemini

## Prerequisites

- Postgres + Redis (cache + queue) running via `docker-compose up`.
- Alembic migration `0003_phase5_usage_events` applied.
- Celery worker + Beat running (for the cost-meter task to write).
- At least one conversation in the DB with `>= 1` user message.

```powershell
cd apps/api
.\.venv\Scripts\Activate.ps1
# Apply migration
python -m alembic upgrade head
# Start Celery worker + Beat in two terminals
python -m celery -A app.workers.celery_app worker --loglevel=info
python -m celery -A app.workers.celery_app beat --loglevel=info
```

## Running

```powershell
# Conversation must exist and have at least one user message.
python -m app.tools.chaos_test <conversation_id>

# Fast iteration — skip the 65s TTL wait:
python -m app.tools.chaos_test <conversation_id> --skip-wait
```

## Verification SQL

The chaos test drives `run_with_fallback` directly without persisting an assistant
message, so the cost-meter Celery task is never triggered and `usage_events` won't
show a fallback row from the chaos run itself. To verify `was_fallback=true` in
the table, send a real message via the chat UI while keeping the chaos patch active
(or observe existing rows from a prior UI turn where fallback occurred naturally).

To confirm the table has rows from real turns:

```powershell
docker exec synq-postgres-1 psql -U synq -d synq_dev -c "
SELECT ts, provider, was_fallback, fallback_from, fallback_reason,
       prompt_tokens, completion_tokens, cost_usd
FROM usage_events
ORDER BY ts DESC LIMIT 5;"
```

Expected for a fallback row: `was_fallback = true`, `fallback_from = '<primary provider>'`,
`provider = '<next provider in chain>'`.

## Verification Redis (cache instance, db 0)

```powershell
redis-cli -p 6379
> EXISTS circuit:gemini
(integer) 1
> EXISTS circuit:gemini:degraded
(integer) 1
> PTTL circuit:gemini:degraded
(integer) 58000  # roughly 60000 then decaying
```

After 65 seconds:

```
> EXISTS circuit:gemini:degraded
(integer) 0
```
