# Deploying SYNQ for free (never-sleeps)

This guide takes you from "runs on my laptop" to **a public link that's always
on, costs $0/month, and needs nothing started locally.**

## The shape of it

| Piece | Host | Free? | Sleeps? |
|-------|------|-------|---------|
| Web frontend (`apps/web`) | **Vercel** | ✅ | Never |
| API + background jobs (`apps/api`) | **Render** (Docker) | ✅ | Kept awake by a pinger |
| Postgres | **Neon** | ✅ | Never |
| Redis (cache) | **Render Key Value** | ✅ | Never |
| Vector DB | **Qdrant Cloud** | ✅ | Never |
| File storage | **Cloudflare R2** | ✅ | Never |
| Keep-alive pinger | **UptimeRobot** (+ GitHub Action backup) | ✅ | — |

**Your public link = the Vercel URL.** Open it, it works. That's the whole goal.

> **Why these choices / the one tradeoff:** Render's free tier gives ~750
> running-hours per month and 512MB RAM per service. Keeping *one* service
> awake 24/7 ≈ 730 hrs, which just fits. So the frontend goes on Vercel
> (unlimited free, no hours), and the API + Celery worker run as **one**
> Render service with Celery in "eager mode" (jobs run in-process). Big
> file uploads / heavy OCR may be slow on 512MB; everything else is fine.
> If you ever outgrow it, Render's $7/mo plan gives 2GB and you can split
> the worker out — nothing in the code has to change.

---

## Order of operations

Do these in order — later steps need values from earlier ones.

1. Databases & storage (Neon, Qdrant, R2) → collect their URLs/keys
2. Render API (Blueprint) → paste those in → get the API URL
3. Vercel web → point it at the API URL → get your public link
4. Wire the two together (CORS + Clerk) → keep-alive

Keep a scratch note open; you'll collect ~15 values. Each step says **📋 SAVE**
for the ones you'll need later.

---

## 0 — Push this branch to GitHub

Render and Vercel both deploy from GitHub, so the repo must be there first.

```bash
git add -A
git commit -m "Add deployment configuration"
git push
```

If the repo isn't on GitHub yet: create an empty repo at github.com, then
`git remote add origin <url>` and `git push -u origin master`.

---

## 1 — Postgres on Neon (free, never sleeps)

1. Sign up at **https://neon.tech** (sign in with GitHub).
2. **Create a project** — name it `synq`, pick the region closest to you.
3. After it's created, open **Connection Details** (or the **Connect** button).
4. Toggle **Connection pooling: ON** and copy the **pooled** connection string.
   It looks like:
   ```
   postgresql://synq_owner:XXXX@ep-cool-name-pooler.us-east-2.aws.neon.tech/synq?sslmode=require
   ```
   - ✅ It must contain `-pooler` in the host.
   - ✅ Keep the `?sslmode=require` at the end (the app needs it).
5. **📋 SAVE** this as `DATABASE_URL`.

> Migrations run automatically when the API boots (in `start.sh`), so you
> don't have to run Alembic by hand.

---

## 2 — Vector DB on Qdrant Cloud (free, never sleeps)

1. Sign up at **https://cloud.qdrant.io**.
2. **Create a free cluster** (the 1GB free tier). Pick a nearby region.
3. When it's running, open the cluster and copy:
   - **Cluster URL** — e.g. `https://abc123.us-east.cloud.qdrant.io:6333`
     (include the `:6333`).
   - **API key** — under **Data Access Control** / **API Keys**, create one.
4. **📋 SAVE** as `QDRANT_URL` and `QDRANT_API_KEY`.

---

## 3 — File storage on Cloudflare R2 (free, never sleeps)

1. Sign up / log in at **https://dash.cloudflare.com**.
2. Left sidebar → **R2** → **Create bucket** → name it `synq-files`.
   (R2 needs you to add a payment card for verification, but the free tier —
   10GB storage — does not charge. If you'd rather not, see the Supabase
   Storage alternative at the bottom.)
3. Get your **Account ID**: on the R2 overview page, the S3 API endpoint is
   shown as `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.
   **📋 SAVE** that whole URL as `S3_ENDPOINT`.
4. **Manage R2 API Tokens** → **Create API token** → permission **Object
   Read & Write** → scope to the `synq-files` bucket → **Create**.
   - Copy **Access Key ID** → **📋 SAVE** as `S3_ACCESS_KEY`.
   - Copy **Secret Access Key** → **📋 SAVE** as `S3_SECRET_KEY`.
5. `S3_BUCKET` = `synq-files`.

---

## 4 — Provider keys (all free, you may already have these)

Grab these if you don't have them — all signup-only, no card:

- **Gemini** → https://aistudio.google.com/apikey → `GEMINI_API_KEY`
- **Mistral** → https://console.mistral.ai (used for embeddings) → `MISTRAL_API_KEY`
- **Groq** → https://console.groq.com/keys (summaries + image descriptions) → `GROQ_API_KEY`

**📋 SAVE** all three.

---

## 5 — Clerk auth (you likely already have an app)

From **https://dashboard.clerk.com** → your app:

- **API Keys** page:
  - **Publishable key** (`pk_...`) → for Vercel (`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`)
  - **Secret key** (`sk_...`) → for Vercel (`CLERK_SECRET_KEY`)
- **API Keys → Advanced** (or "Show JWT public key" / JWKS):
  - **JWKS URL** → `CLERK_JWKS_URL`
    (looks like `https://<instance>.clerk.accounts.dev/.well-known/jwks.json`)
  - **Frontend API URL** → `CLERK_ISSUER` (the same host, no trailing slash,
    e.g. `https://<instance>.clerk.accounts.dev`)
- **Webhooks** (optional, can do later): create an endpoint at
  `https://<your-render-api>/webhooks/clerk` for `user.created` + `user.deleted`,
  copy the **Signing Secret** → `CLERK_WEBHOOK_SECRET`.
  (You can leave this blank at first — the API lazily creates user rows on
  first request.)

**📋 SAVE** all of these.

---

## 6 — Deploy the API on Render (Blueprint)

1. Sign up at **https://render.com** (sign in with GitHub, authorize your repo).
2. **New ▸ Blueprint** → select this repository → Render detects `render.yaml`.
3. It will show **synq-api** (web) and **synq-redis** (key value). Click
   **Apply**. Render now asks you to fill in every `sync: false` variable —
   paste from your saved notes:

   | Variable | Value |
   |----------|-------|
   | `DATABASE_URL` | Neon pooled string (step 1) |
   | `S3_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` | R2 (step 3) |
   | `QDRANT_URL` / `QDRANT_API_KEY` | Qdrant (step 2) |
   | `GEMINI_API_KEY` / `MISTRAL_API_KEY` / `GROQ_API_KEY` | step 4 |
   | `CLERK_JWKS_URL` / `CLERK_ISSUER` / `CLERK_WEBHOOK_SECRET` | step 5 |
   | `CORS_ORIGINS` | put `["http://localhost:3000"]` for now — you'll fix it in step 8 |

   (`SECRET_KEY`, `REDIS_URL`, `REDIS_QUEUE_URL` are filled automatically.)

4. Click **Apply / Create**. First build takes ~5–8 min (it installs
   Tesseract + Python deps and runs migrations on boot).
5. When it's live, open the service → copy its URL, e.g.
   `https://synq-api.onrender.com`. **📋 SAVE** as your **API URL**.
6. Test it: visit `https://synq-api.onrender.com/health` → you should see
   `{"status":"ok"}`.

> **If the Blueprint errors on the `keyvalue` service:** some Render accounts
> use the older type name. Open `render.yaml`, change `type: keyvalue` to
> `type: redis`, push, and re-apply. (Or just create a free **Key Value**
> instance manually in the dashboard and set `REDIS_URL` + `REDIS_QUEUE_URL`
> to its Internal connection string.)

---

## 7 — Deploy the web app on Vercel

1. Sign up at **https://vercel.com** (sign in with GitHub).
2. **Add New ▸ Project** → import this repo.
3. **Root Directory** → click **Edit** → choose **`apps/web`**. Framework
   preset should auto-detect **Next.js**. Leave build/install commands default
   (Vercel handles the npm workspace and `@synq/shared-types` automatically).
4. Expand **Environment Variables** and add (from `apps/web/.env.production.example`):

   | Variable | Value |
   |----------|-------|
   | `NEXT_PUBLIC_API_URL` | your Render API URL (no trailing slash) |
   | `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk `pk_...` |
   | `CLERK_SECRET_KEY` | Clerk `sk_...` |
   | `NEXT_PUBLIC_CLERK_SIGN_IN_URL` | `/sign-in` |
   | `NEXT_PUBLIC_CLERK_SIGN_UP_URL` | `/sign-up` |
   | `NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL` | `/chat` |
   | `NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL` | `/chat` |

5. **Deploy.** When done, Vercel gives you a URL like
   `https://synq-web.vercel.app`. **📋 SAVE** it — **this is your public link.** 🎉
6. Add it back as `NEXT_PUBLIC_APP_URL` in Vercel env vars (then redeploy once),
   so the app knows its own address.

---

## 8 — Connect the two (CORS + Clerk allowed origins)

The browser will block the frontend from calling the API until the API
trusts that origin.

1. **Render** → synq-api → **Environment** → set:
   ```
   CORS_ORIGINS = ["https://synq-web.vercel.app"]
   ```
   (your exact Vercel URL, JSON array, no trailing slash). Save → it redeploys.
2. **Clerk** → your app → add the Vercel domain to the allowed origins /
   production instance (Clerk dashboard → **Domains** / **Paths**). For a
   quick start the Clerk *development* instance keys work on any domain; for
   a real launch, create a **production** instance and use its `pk_live`/
   `sk_live` keys + add your Vercel domain.

Now open your Vercel link → **Sign up** → you should land on `/chat` and be
able to send a message that streams back. Refresh — history reloads. ✅

---

## 9 — Make it never sleep (the pinger)

**UptimeRobot (primary — 2 minutes):**

1. Sign up at **https://uptimerobot.com** (free).
2. **Add New Monitor** → type **HTTP(s)** → URL =
   `https://synq-api.onrender.com/health` → interval **5 minutes** → Create.

That's it — it pings every 5 min, so Render never idles long enough to sleep,
and it emails you if the API ever goes down.

**GitHub Action (backup — already in this repo):**

`.github/workflows/keepalive.yml` pings every ~10 min too. To enable it:
- GitHub repo → **Settings ▸ Secrets and variables ▸ Actions ▸ New secret**
- Name `API_HEALTH_URL`, value `https://synq-api.onrender.com/health`.
  (Reminder: GitHub disables scheduled workflows after 60 days of repo
  inactivity — UptimeRobot is the dependable one; this is just a safety net.)

---

## Done ✅

From now on: **open the Vercel link.** Nothing to start locally, nothing to
keep running on your laptop. The API stays warm, the databases never sleep,
and it's all on free tiers.

### Day-2 notes

- **Pushing updates:** `git push` → Render rebuilds the API and Vercel
  rebuilds the web automatically.
- **Logs:** Render → synq-api → **Logs**. Vercel → project → **Logs**.
- **First request after a deploy** can take ~30–50s (fresh container); the
  pinger keeps it warm afterward.
- **Heavy file OCR feels slow / the API restarts:** that's the 512MB limit in
  eager mode. Upgrade Render to Starter ($7/mo, 2GB) and optionally split the
  Celery worker into its own service — set `CELERY_EAGER=false` and add a
  `worker` service running `uv run celery -A app.workers.celery_app worker`.
- **Things not deployed (don't need to be):** Jaeger tracing and the MinIO
  console are local-dev conveniences only; the app runs fine without them.

### Alternative to Cloudflare R2 (no card)

If you don't want to add a card to Cloudflare, use **Supabase Storage**
(S3-compatible, free, no card): create a Supabase project → **Storage** →
create a bucket named `synq-files` → **Project Settings → Storage → S3
Connection**: copy the **endpoint** (`https://<ref>.storage.supabase.co/storage/v1/s3`)
and the **region**, then create **S3 access keys** there. Map them to
`S3_ENDPOINT` / `S3_REGION` / `S3_ACCESS_KEY` / `S3_SECRET_KEY`. The
`S3_REGION` **must** match the project region (Supabase validates it in the
request signature). The code path is otherwise identical (S3 v4, path-style).
