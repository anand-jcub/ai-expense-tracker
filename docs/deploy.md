# Deploy / remote access

## Recommended: Cloudflare Tunnel (free, no deposit)

Run the app on this PC and expose it with a free HTTPS URL. **No Google billing, no card, no Docker.**

```cmd
cd C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai
tunnel.cmd
```

| | |
|--|--|
| Cost | Free |
| Needs | PC **on** and local app on port `8765` |
| URL | `https://….trycloudflare.com` (new URL each restart) |
| Stop | `stop-tunnel.cmd` |
| Saved | Current URL in `tunnel.url` |

`tunnel.cmd` starts the local app if needed, installs `cloudflared` if missing, and prints Login / Health links.

**Security:** Anyone with the URL can hit the login page. Use a strong password. Restarting the tunnel changes the URL.

---

## Optional later: Google Cloud Run

Host the full app in a container (PC can be off). Needs a GCP project + **billing linked** (often a deposit/card in India). Heavy for personal use — prefer the tunnel above unless you need always-on without this PC.

**No local Docker required** — Cloud Build builds from the `Dockerfile` via `gcloud run deploy --source`.

Scale-to-zero keeps cost near **$0** within [Cloud Run free tier](https://cloud.google.com/run/pricing) after billing is linked.

## Cloud Run one command (interactive Windows Terminal)

```cmd
cd C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai
deploy-gcp.cmd
```

or:

```powershell
cd C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy-gcp.ps1
```

This will:

1. Install **Google Cloud SDK** via winget if missing  
2. `gcloud auth login` (browser)  
3. Use/set a GCP **project**  
4. Enable Cloud Run, Cloud Build, Artifact Registry, Storage  
5. Create a **GCS bucket** `{project}-expense-data` and mount it at `/data`  
6. Deploy with `max-instances=1` (safe for SQLite) and `min-instances=0` (scale to zero)  
7. Print HTTPS URL + open the service  

First build often takes **5–10 minutes**.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | platform sets (`8080`) | Listen port |
| `DATA_DIR` | `/data` on Cloud Run | SQLite (`users.db`, `expenses_*.db`) |
| `COOKIE_SECURE` | `1` in production | Secure cookies behind HTTPS |
| `ENV` | `production` | Enables production cookie behavior |

## Manual deploy (if you already have gcloud)

```powershell
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com

# Durable data (optional but recommended)
$Bucket = "YOUR_PROJECT_ID-expense-data"
gcloud storage buckets create "gs://$Bucket" --location asia-south1 --uniform-bucket-level-access

gcloud run deploy expense-tracker `
  --source . `
  --region asia-south1 `
  --allow-unauthenticated `
  --memory 512Mi `
  --cpu 1 `
  --min-instances 0 `
  --max-instances 1 `
  --set-env-vars "ENV=production,COOKIE_SECURE=1,DATA_DIR=/data" `
  --add-volume name=expensedata,type=cloud-storage,bucket=$Bucket `
  --add-volume-mount volume=expensedata,mount-path=/data
```

### Ephemeral demo only (no bucket)

```bash
gcloud run deploy expense-tracker \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars "ENV=production,COOKIE_SECURE=1,DATA_DIR=/tmp/data" \
  --memory 512Mi --cpu 1 --min-instances 0 --max-instances 1
```

**Warning:** `/tmp` is wiped when the instance scales to zero or is replaced.

## Data notes (SQLite on Cloud Run)

- Cloud Run **local disk is ephemeral**. The deploy script mounts a **GCS bucket** at `/data`.
- Keep **`max-instances=1`** so only one process writes SQLite (GCS FUSE has weak locking).
- Cloud DB starts **empty**. To seed from this PC after first deploy:

```powershell
gcloud storage cp data\users.db gs://YOUR_PROJECT_ID-expense-data/users.db
gcloud storage cp "data\expenses_anand.db" gs://YOUR_PROJECT_ID-expense-data/expenses_anand.db
# then restart the revision if needed:
gcloud run services update expense-tracker --region asia-south1
```

- For multi-device / concurrent writers, plan **Phase 2 Neon/Postgres** (see roadmap).

## After deploy

1. Open the printed HTTPS URL → `/login`  
2. Register a user (or upload SQLite as above)  
3. Hit `/api/health`  
4. Create API tokens for MCP/mobile — see [api.md](api.md)

## Docker local (optional)

Only if Docker Desktop is installed:

```powershell
docker build -t expense-tracker .
docker run --rm -p 8080:8080 `
  -e PORT=8080 -e DATA_DIR=/data -e COOKIE_SECURE=0 -e ENV= `
  -v "${PWD}/data:/data" `
  expense-tracker
```

## Fly.io (optional / not primary)

Fly requires a payment method for new accounts and is no longer the default path.
Scripts remain: `deploy.cmd` / `deploy.ps1` + `fly.toml`. Prefer **Google Cloud** above.

## Roadmap

| Phase | What |
|-------|------|
| 0 | Container on Cloud Run + GCS data (this doc) |
| 1 | API tokens ✅ + optional static React on Cloudflare Pages |
| 2 | Neon/Turso instead of SQLite on FUSE |
| 3 | MCP stdio tools ✅ — see [mcp.md](mcp.md) |
| 4 | PWA mobile |
| 5 | AI agent via same tools/APIs |

Architecture rule: **domain stays in Python**; MCP/mobile never reimplement `get_balance`.

## Tools on this machine

| Tool | Needed for GCP? |
|------|-----------------|
| `gcloud` (Google Cloud SDK) | **Yes** — installed by `deploy-gcp.cmd` |
| Docker Desktop | No (Cloud Build builds the image) |
| flyctl | No |
