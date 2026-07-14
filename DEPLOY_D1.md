# Deploying linkding with Cloudflare D1

This guide walks through getting Cloudflare D1 credentials and deploying linkding
to Render or Railway using them. It complements the shorter reference at
[`docs/src/content/docs/deploying-with-d1.md`](docs/src/content/docs/deploying-with-d1.md)
and the options reference in [`docs/src/content/docs/options.md`](docs/src/content/docs/options.md).

## What you'll end up with

Three values, which get set as environment variables on whichever platform you deploy to:

| Variable               | What it is                                          |
|-------------------------|------------------------------------------------------|
| `LD_CF_ACCOUNT_ID`       | Your Cloudflare account ID                          |
| `LD_CF_D1_DATABASE_ID`   | The ID of the D1 database linkding will use          |
| `LD_CF_API_TOKEN`        | An API token allowed to read/write that database     |

And `LD_DB_ENGINE=d1` to tell linkding to use them instead of SQLite.

---

## 1. Get your Cloudflare account ID

1. Log in to the [Cloudflare dashboard](https://dash.cloudflare.com).
2. On the **Account Home** page, find your account name in the sidebar/list.
3. Click the "..." (menu) button next to your account name and choose **Copy account ID**.

Alternatively, open **Workers & Pages** in the sidebar — the **Account details** panel
on that page also shows the Account ID with a copy button.

Save this value as `LD_CF_ACCOUNT_ID`.

## 2. Create a D1 database

**Option A — Dashboard:**

1. In the sidebar, go to **Storage & Databases > D1 SQL Database** (or **Workers & Pages > D1** on older dashboards).
2. Click **Create Database**.
3. Give it a name, e.g. `linkding`.
4. Optionally pick a location hint close to where you're deploying.
5. Click **Create**.
6. On the database's detail page, copy the **Database ID** (a UUID) shown near the top.

**Option B — Wrangler CLI:**

```shell
npm install -g wrangler
wrangler login
wrangler d1 create linkding
```

The command prints a `database_id` in its output — that's the value you need.

Save this value as `LD_CF_D1_DATABASE_ID`.

## 3. Create an API token

1. In the Cloudflare dashboard, go to **My Profile > API Tokens** (top-right avatar menu),
   or **Manage Account > API Tokens** if you want an account-scoped token.
2. Click **Create Token**.
3. Choose **Create Custom Token** (don't use a template).
4. Give it a name, e.g. `linkding-d1`.
5. Under **Permissions**, add: **Account** → **D1** → **Edit**.
6. Under **Account Resources**, restrict it to the specific account (recommended)
   rather than "All accounts".
7. Optionally set a **TTL** (expiration) if you want to rotate it later.
8. Click **Continue to summary**, review, then **Create Token**.
9. **Copy the token immediately** — Cloudflare only shows it once.

Save this value as `LD_CF_API_TOKEN`. Treat it like a password: never commit it to
git or paste it into a public place. Use each platform's secret/env-var storage
(see below), not the repo.

---

## 4. Deploy to Render (free tier)

The repo's `render.yaml` [Blueprint](https://render.com/docs/blueprint-spec) is
configured for Render's **free** web service plan (`plan: free`), so this costs
nothing to run.

1. Push this repository (or your fork of it) to GitHub/GitLab.
2. In the [Render dashboard](https://dashboard.render.com), click **New > Blueprint**.
3. Select the repository. Render will detect `render.yaml`.
4. When prompted, fill in:
   - `LD_CF_ACCOUNT_ID`
   - `LD_CF_D1_DATABASE_ID`
   - `LD_CF_API_TOKEN`
   - `LD_SUPERUSER_NAME` / `LD_SUPERUSER_PASSWORD` (optional, creates an admin user on first boot)
5. Click **Apply**. Render builds the Docker image and deploys it.
6. Once live, open the service URL and log in.

Render automatically injects a `PORT` environment variable; the container picks it
up automatically (no extra config needed — this was wired up in `bootstrap.sh`).

### Free tier tradeoffs

- **No persistent disk.** Render's free plan doesn't support attaching a disk, so
  the container's local `data/` folder (favicons, preview images, HTML snapshots)
  is wiped on every restart or redeploy. Your actual bookmarks, tags, and users
  are unaffected since they live in D1 — you'll just see favicons/previews
  re-download after a restart. If you want those to persist too, upgrade the
  service to a paid plan (`starter` or above) and add a `disk:` block back to
  `render.yaml` mounting `/etc/linkding/data`.
- **Spins down after 15 minutes of inactivity** and takes about a minute to wake
  back up on the next request.
- **750 free instance-hours per month**, which comfortably covers one always-on
  low-traffic service.

## 5. Deploy to Railway

Railway doesn't have a good long-term free option for this: volumes created
during the free trial are deleted 30 days after the trial credits expire, and
the ongoing free plan only grants $1/month in credit. Prefer Render's free
tier (above) for a genuinely free deployment; use Railway if you're fine with
its usage-based paid plan instead.

The repo includes a `railway.json` config that points Railway at
`docker/default.Dockerfile`. Railway's config-as-code doesn't support declaring
environment variables or volumes, so those two steps are manual.

1. In the [Railway dashboard](https://railway.app/dashboard), click **New Project > Deploy from GitHub repo**.
2. Select this repository (or your fork). Railway detects `railway.json` and
   builds the Dockerfile automatically.
3. Open the new service's **Variables** tab and add:
   - `LD_DB_ENGINE=d1`
   - `LD_CF_ACCOUNT_ID`
   - `LD_CF_D1_DATABASE_ID`
   - `LD_CF_API_TOKEN`
   - `LD_SUPERUSER_NAME` / `LD_SUPERUSER_PASSWORD` (optional)
4. Open the **Volumes** tab (or Settings > Volumes) and attach a volume mounted
   at `/etc/linkding/data`, if you're on a paid plan (not available/durable on
   the free trial, see above).
5. Deploy. Railway also injects a `PORT` variable that the container picks up
   automatically.

---

## Verifying it worked

Once deployed, check that linkding is actually talking to D1 and not silently
falling back to SQLite:

- Open the app and create a bookmark — then check the D1 dashboard's **Console**
  tab (or `wrangler d1 execute linkding --command "select * from bookmarks_bookmark"`)
  to confirm the row landed in D1.
- If the deploy fails at startup with `ImproperlyConfigured: The Cloudflare D1
  backend requires the account_id, database_id and api_token options`, double
  check all three `LD_CF_*` variables are set on the service.

## Notes and limitations

- The D1 HTTP API executes every request in its own implicit transaction and
  doesn't support interactive transactions (`BEGIN`/`COMMIT`/`ROLLBACK`). This is
  transparent for normal linkding usage but means multi-step operations aren't
  atomic at the database level.
- D1 caps queries at 100 bound parameters; linkding's D1 backend automatically
  falls back to inlining values as escaped SQL literals for larger queries
  (e.g. big `IN (...)` filters), so this doesn't require any action on your part.
- Favicons, preview images, and HTML snapshots are still stored on the local
  filesystem under `data/`, independent of the database backend. On Render's
  free plan (and Railway's free trial) that folder is ephemeral; only your
  bookmark data in D1 survives restarts. Attach a persistent disk/volume on a
  paid plan if you need those local files to persist too.
- Cloudflare D1's free tier (5GB storage, 5M reads/100K writes per day) doesn't
  require a paid Cloudflare plan and comfortably covers a personal bookmark
  manager.
