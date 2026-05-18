# SYNQ

Cross-agent conversation continuity SaaS. Users continue conversations across AI providers (Claude, GPT, Gemini) when they hit rate limits, want to switch models, or need different capabilities.

**Current status: Pre-Phase 1 — skeleton only. No features implemented.**

---

## Repository layout

```
synq/
├── apps/
│   ├── web/              # Next.js 14 · App Router · TypeScript · Tailwind · Zustand · shadcn/ui
│   └── api/              # FastAPI · Python 3.12 · uv
├── packages/
│   └── shared-types/     # TypeScript types mirroring Pydantic models (no code-gen yet)
├── docker-compose.yml    # Postgres 16 · Redis 7 (×2) · MinIO
├── .github/workflows/    # CI: lint + typecheck only
└── .pre-commit-config.yaml
```

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Node.js | ≥ 22 | https://nodejs.org |
| Python | ≥ 3.12 | https://python.org |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (Mac/Linux) · [Windows](https://docs.astral.sh/uv/getting-started/installation/) |
| Docker Desktop | latest | https://docker.com |
| pre-commit (optional) | latest | `pip install pre-commit` |

---

## Local setup

### 1 — Clone and copy env files

```bash
git clone <repo-url> synq && cd synq
cp .env.example .env
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env.local
```

### 2 — Start infrastructure

```bash
docker compose up -d
```

Services started:
| Service | URL |
|---------|-----|
| Postgres 16 | `localhost:5432` |
| Redis (cache) | `localhost:6379` |
| Redis (queue) | `localhost:6380` |
| MinIO S3 API | `localhost:9000` |
| MinIO console | `localhost:9001` (user: `synq_minio` / pass: `synq_minio_password`) |

### 3 — Install JS dependencies

```bash
npm install   # from repo root — installs apps/web + packages/*
```

### 4 — Install Python dependencies

```bash
cd apps/api
uv sync       # creates .venv, installs runtime + dev deps
cd ../..
```

### 5 — (Optional) Set up pre-commit hooks

```bash
pre-commit install
```

---

## Running locally

**API** (from `apps/api/`):
```bash
uv run uvicorn app.main:app --reload --port 8000
# → http://localhost:8000/health
# → http://localhost:8000/docs  (Swagger UI)
```

**Web** (from repo root):
```bash
npm run dev:web
# → http://localhost:3000
```

---

## Useful commands

| Command | What it does |
|---------|-------------|
| `npm run lint` | ESLint on apps/web |
| `npm run typecheck` | tsc --noEmit on apps/web + shared-types |
| `npm run format` | Prettier across all TS/JSON/MD files |
| `cd apps/api && uv run ruff check .` | Lint Python |
| `cd apps/api && uv run ruff format .` | Format Python |
| `cd apps/api && uv run mypy app/` | Type-check Python |
| `cd apps/api && uv run pytest` | Run API tests |
| `docker compose down -v` | Stop infra and wipe volumes |

---

## Adding shadcn/ui components

After running `npm install`:
```bash
cd apps/web
npx shadcn@latest add button
npx shadcn@latest add input
# etc.
```

Components land in `apps/web/components/ui/`.

---

## Build sequence (six phases)

Each phase is independently shippable. Do not skip ahead.

### Phase 1 — Foundation (weeks 1–2)
**Deliverables**
- Clerk auth with FastAPI middleware
- Postgres schema with indexes and `version` column
- Conversation service REST endpoints
- LiteLLM wired for Anthropic only
- Next.js client with Zustand and SSE streaming

**Definition of done:** Logged-in user can have a multi-turn streaming chat with Claude. Page refresh restores history.

---

### Phase 2 — Multi-provider (weeks 3–4)
**Deliverables**
- `ProviderAdapter` protocol defined
- OpenAI and Gemini adapters via LiteLLM
- Per-provider token counting with caching
- Model picker UI
- Naïve truncation (drop oldest) when over context

**Definition of done:** User can switch from Claude to Gemini mid-conversation on threads under 50 turns and it works.

---

### Phase 3 — Multimodal (weeks 5–6)
**Deliverables**
- File upload to S3 / R2
- Celery worker for parse + OCR + vision description
- `files` table with `extracted_text` and `description` columns
- Adapter logic: vision target gets bytes, text target gets description
- PDF chunking with stored chunk metadata

**Definition of done:** User uploads an image to a Claude conversation, switches to a text-only provider, and the new model knows what was in the image.

---

### Phase 4 — Intelligence (weeks 7–9) — _the differentiator_
**Deliverables**
- Embedder worker writing to Qdrant
- Rolling-summary worker (Haiku-powered, runs every 10 turns)
- Fact-extraction worker
- RAG retriever in context engine
- Six-part compression assembly wired into context engine
- Test fixtures with 300+ turn conversations

**Definition of done:** Long conversations with images, documents, and many turns switch providers without the new model losing context.

---

### Phase 5 — Resilience (weeks 10–11)
**Deliverables**
- Provider router with per-user fallback chains
- Redis-backed circuit breakers
- Cost-meter Celery worker writing to ClickHouse
- Admin dashboard for spend by user/provider/feature
- Per-user daily cost ceilings at gateway

**Definition of done:** Killing Anthropic in a fire drill auto-continues conversations on Gemini. One user cannot bankrupt you.

---

### Phase 6 — Productionalize (weeks 12–14)
**Deliverables**
- OpenTelemetry instrumentation across all services
- Sentry for unhandled exceptions
- Stripe usage-based billing tied to ClickHouse events
- PostHog feature flags with prompt A/B test infrastructure
- Audit log table and access middleware
- Security review and SOC2 evidence collection started

**Definition of done:** Launch-ready.

---

### Post-launch
- Conversation forking (copy-on-write at DB level)
- Multi-device sync with WebSocket presence
- MCP tool integration
- BYOK for enterprise
- Fine-tuned routing models

---

## Tech stack

| Layer | Choice |
|-------|--------|
| Edge | Cloudflare |
| Frontend | Next.js 14, Zustand, TailwindCSS, shadcn/ui |
| Auth | Clerk (Phase 1) |
| Backend | FastAPI (Python 3.12) |
| LLM SDK | LiteLLM + custom adapters |
| Database | Postgres 16 (Supabase / Neon / RDS) |
| Cache & queue | Redis 7 — two instances |
| Vector DB | Qdrant |
| Object storage | Cloudflare R2 / AWS S3 |
| Analytics DB | ClickHouse |
| Async workers | Temporal (durable) + Celery (one-shot) |
| Telemetry | OpenTelemetry + Grafana + Sentry |
| Billing | Stripe |
| Feature flags | PostHog |
| Deployment | Kubernetes or Render / Railway |
