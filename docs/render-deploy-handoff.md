# Render deploy handoff (hackathon)

Deploy the Kantipur demo as two Render services on the free Hobby plan. Do not
use GoDaddy hosting, Streamlit, Vercel for the API, or Docker. Use the GoDaddy
code only for a domain, and only after the `onrender.com` URLs work.

The dashboard is a static Vite build. The API is a long-lived FastAPI process.
They must be separate Render services. `VITE_API_BASE_URL` is baked in at
frontend build time, so create the API first.

## What you are deploying

| Piece | Render type | Runs |
| --- | --- | --- |
| FastAPI | Web Service, Free instance | `uvicorn apps.api.main:app` |
| Dashboard | Static Site | `apps/web/dist` |

Repo root is the root directory for **both** services. The web app depends on
`packages/shared-types` via a relative `file:` path.

Do not deploy `services/physics`. The API reads frozen fixtures under
`data/scenarios/kantipur-river/`.

## 0. Prerequisites

- GitHub repo the deployer can access (Render deploys from Git).
- Render account on the **Hobby** plan.
- Node is not required on your laptop if Render builds the frontend.
- The PMTiles archive is gitignored. The static-site build must fetch it.

## 1. API web service

Dashboard → **New → Web Service** → this repo.

| Field | Value |
| --- | --- |
| Language | Python 3 |
| Python version | `3.12` |
| Root directory | *leave blank* (repository root) |
| Branch | the branch judges should see |
| Instance type | **Free** |
| Build command | `pip install "fastapi>=0.115,<1" "pydantic>=2.11,<3" "uvicorn>=0.34,<1"` |
| Start command | `uvicorn apps.api.main:app --host 0.0.0.0 --port $PORT` |

Environment:

| Key | Value |
| --- | --- |
| `THE_ARK_CORS_ORIGINS` | temporarily `https://placeholder.example` — replace in step 3 |
| `THE_ARK_REPORT_DB_PATH` | `/tmp/the-ark.sqlite3` |

Free instances have an ephemeral disk. Reports will not survive sleep or
redeploy. Fixture-backed routing, isolation, plans, and the bridge-failure
event do not need the database.

Create the service, wait until it is live, and copy the URL
(`https://something.onrender.com`).

Verify:

```text
GET https://<api>.onrender.com/health
GET https://<api>.onrender.com/scenarios/kantipur-river/bootstrap
GET https://<api>.onrender.com/docs
```

`/health` must return `{"status":"ok"}`. The first request after idle can take
about a minute (free instance spin-up). Bootstrap is ~1.8 MB JSON; if it 502s
once, retry.

## 2. Dashboard static site

Dashboard → **New → Static Site** → same repo.

| Field | Value |
| --- | --- |
| Root directory | *leave blank* (repository root) |
| Build command | see below |
| Publish directory | `apps/web/dist` |

Build command (paste as one block):

```bash
chmod +x scripts/fetch-basemap.sh && ./scripts/fetch-basemap.sh; rm -f package-lock.json; npm install; VITE_API_BASE_URL=https://<api>.onrender.com npm exec --workspace apps/web -- vite build
```

Replace `<api>` with the API hostname from step 1. No trailing slash.

Why this command is not `npm run build:web`:

- `apps/web` `build` runs `tsc`. TypeScript 7 ships a native binary that the
  macOS lockfile does not install on Linux, so typecheck fails on Render.
- The lockfile only records Darwin optional native bindings (Rolldown,
  Lightningcss, Tailwind Oxide). `npm ci` on Linux will not compile Vite.
  Deleting `package-lock.json` in the **build environment only** lets npm
  fetch Linux binaries. Do not commit that deletion.
- `./scripts/fetch-basemap.sh` writes
  `apps/web/public/basemap/kantipur.pmtiles` (~18 MB). Vite copies `public/`
  into `dist`. If the fetch fails, the dashboard still boots and falls back
  to the schematic map.

Redirects / rewrites (Static Site → Redirects/Rewrites):

| Source | Destination | Action |
| --- | --- | --- |
| `/command-center` | `/index.html` | Rewrite |

Without that rewrite, `https://<web>.onrender.com/command-center` is a 404.

Create the site. Copy the URL (`https://something-web.onrender.com`).

## 3. CORS

Back on the API service → Environment:

```text
THE_ARK_CORS_ORIGINS=https://<web>.onrender.com
```

No trailing slash. Save. Render restarts the API.

If you later attach a GoDaddy domain to the static site, add that origin too,
comma-separated:

```text
THE_ARK_CORS_ORIGINS=https://<web>.onrender.com,https://yourdomain.com,https://www.yourdomain.com
```

## 4. Verify the demo

1. Open `https://<web>.onrender.com`. Landing page should load.
2. Open `https://<web>.onrender.com/command-center`.
3. You should see communities, Plan A/B/C, and the timeline. If this is the
   first hit after idle, wait for the API to wake (~1 min) and refresh.
4. Inject the East River Bridge failure. The world-state version should change.
5. Optional: Reports → run a simulation. It may work for the session and then
   vanish after sleep; that is expected on Free.

If the map is a schematic with a “basemap unavailable” notice, the PMTiles
fetch failed. The scenario is still demoable. Re-run the static build after
checking `scripts/fetch-basemap.sh` output in the Render build logs.

## 5. Optional GoDaddy domain

Redeem the hackathon code for a **domain only**. Do not use GoDaddy Web
Hosting, Website Builder, or Airo.

On the Render static site, add the custom domain. In GoDaddy DNS:

- `CNAME` `www` → the Render static hostname they show you
- Follow Render’s instructions for apex `@` (often an ANAME/ALIAS, not a raw A)

Then append `https://yourdomain.com` to `THE_ARK_CORS_ORIGINS` and rebuild
nothing else unless you also want the frontend to call a custom API host.

## Judge-day notes

- Ping `/health` a minute before demo so the free API is warm.
- Hobby includes 750 free instance hours/month, 5 GB bandwidth, 500 build
  minutes. A weekend demo stays inside that.
- Do not enable auto-deploy from every push unless you want surprise rebuilds
  during judging.
- Physics, CatBoost, and `data/models/*.pkl` are not required at runtime.

## Failure cheat sheet

| Symptom | Likely cause |
| --- | --- |
| API deploy fails on import | Start command not run from repo root; missing `apps/` or `data/scenarios/` |
| `Unable to resolve @typescript/typescript-linux-*` | Build used `npm run build` / `tsc`. Use `vite build` only. |
| `Cannot find native binding` / Rolldown / Oxide | `npm ci` with the Darwin lockfile. Use `rm -f package-lock.json && npm install`. |
| Dashboard loads, every API call fails | `VITE_API_BASE_URL` missing, wrong, or trailing slash. Rebuild the static site. |
| Browser CORS error | `THE_ARK_CORS_ORIGINS` does not exactly match the dashboard origin. |
| `/command-center` 404 | Missing rewrite to `/index.html`. |
| Schematic map only | PMTiles fetch failed; non-blocking for the demo. |
| First load hangs ~60s then works | Free web service cold start. Warm it before judging. |
| Reports empty after a wait | Free disk is ephemeral. Do not demo report history as durable. |

## Out of scope for this handoff

- Docker / compose
- Serving the UI and API on one origin (would need nginx or FastAPI static
  mount; not in the repo)
- Vercel, Streamlit, GoDaddy cPanel
- Paid Render disks or always-on instances
