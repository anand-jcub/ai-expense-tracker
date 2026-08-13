# Deploy (Phase 0) — free, usage-friendly hosting

Host the full app (classic UI + React `/app` + APIs) in one container with **SQLite on a volume**.

Later phases (Neon Postgres, MCP, mobile) build on this API surface — see the hosting plan.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8765` local / platform sets this | Listen port |
| `DATA_DIR` | `./data` | SQLite files (`users.db`, `expenses_*.db`) |
| `COOKIE_SECURE` | off | Set `1` behind HTTPS |
| `ENV` | — | `production` also enables Secure cookies |

## Docker local

```powershell
cd C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai
docker build -t expense-tracker .
docker run --rm -p 8080:8080 `
  -e PORT=8080 `
  -e DATA_DIR=/data `
  -e COOKIE_SECURE=0 `
  -e ENV= `
  -v "${PWD}/data:/data" `
  expense-tracker
```

Open http://127.0.0.1:8080

## Google Cloud Run (free tier, scale-to-zero)

1. Create a project; enable Cloud Run and Artifact Registry.
2. Build and push the image (Cloud Build or local + push).
3. Deploy **with a volume** for SQLite (Cloud Storage FUSE volume or migrate to Postgres in Phase 2).

Minimal deploy (ephemeral disk — **demo only, data may reset**):

```bash
gcloud run deploy expense-tracker \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars "ENV=production,COOKIE_SECURE=1,DATA_DIR=/tmp/data" \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 2
```

**Important:** For durable data on free tier, either:

- Attach a **persistent volume** / mount GCS bucket to `DATA_DIR`, or  
- Plan **Phase 2 Neon Postgres** before real multi-device use.

## Fly.io (recommended for this machine)

`flyctl` is installable via winget. **No local Docker** — Fly uses a remote builder.

### One command (interactive Windows Terminal)

```powershell
cd C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai
.\deploy.ps1
```

This will:

1. Install/login to Fly (browser)  
2. Create app + 1GB volume `expensedata`  
3. `fly deploy --remote-only`  
4. Open `https://<app>.fly.dev`

### Manual steps

```powershell
winget install --id Fly-io.flyctl -e
# restart terminal, then:
flyctl auth login
flyctl apps create expense-tracker-anand --org personal
flyctl volumes create expensedata --region sin --size 1 -a expense-tracker-anand -y
flyctl deploy --remote-only
```

### GitHub Actions (optional)

1. Locally: `flyctl tokens create deploy -x 999999h`  
2. GitHub → repo **Settings → Secrets → Actions** → `FLY_API_TOKEN`  
3. Push to `master` or run workflow **Fly Deploy**

`fly.toml` is already in the repo with `/data` mount + health check on `/api/health`.

## After deploy

1. Open the HTTPS URL → `/login`  
2. Register or use existing user (if you copied `data/` into the volume)  
3. Confirm data still present after redeploy  

## API tokens (Phase 1)

Non-browser clients (MCP, mobile, scripts) use Bearer tokens — see **[docs/api.md](api.md)**.

```http
POST /api/token
Content-Type: application/json

{"username":"…","password":"…","label":"mcp"}
```

Then: `Authorization: Bearer exp_…` on `/api/*`.

## Roadmap after Phase 0

| Phase | What |
|-------|------|
| 0 | Container + volume (this doc) |
| 1 | API tokens ✅ + static React on Cloudflare Pages |
| 2 | Neon/Turso instead of SQLite volume |
| 3 | MCP stdio tools ✅ — see [mcp.md](mcp.md) |
| 4 | PWA mobile |
| 5 | AI agent via same tools/APIs |

Architecture rule: **domain stays in Python**; MCP/mobile never reimplement `get_balance`.

## Deploy tools not on this machine yet

Docker / flyctl / gcloud are optional on the dev PC. Install one of:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [flyctl](https://fly.io/docs/hands-on/install-flyctl/)
- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)

Then use `Dockerfile` + `fly.toml` as above.
