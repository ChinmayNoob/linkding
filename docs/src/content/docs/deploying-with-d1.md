---
title: "Deploying with Cloudflare D1"
description: "How to run linkding with a Cloudflare D1 database, and deploy it to Render or Railway"
---

In addition to SQLite and PostgreSQL, linkding can use [Cloudflare D1](https://developers.cloudflare.com/d1/) as its database.
This is useful when deploying to platforms without persistent local storage for a database file, such as [Render](https://render.com) or [Railway](https://railway.com).

D1 is accessed through Cloudflare's HTTP API rather than a binding, so linkding can talk to it from any hosting provider, not just Cloudflare Workers.

:::note
The D1 HTTP API executes every request in its own implicit transaction and does not support interactive transactions (`BEGIN` / `COMMIT` / `ROLLBACK`).
This is transparent for normal usage of linkding, but means that multi-step operations are not atomic at the database level.
:::

## 1. Create a D1 database

Using the [Cloudflare dashboard](https://dash.cloudflare.com) or `wrangler`:

```shell
wrangler d1 create linkding
```

Note the database ID from the output, or from the dashboard under **Workers & Pages > D1**.

## 2. Create an API token

Create a Cloudflare API token with the **D1:Edit** permission for your account, under **My Profile > API Tokens** in the dashboard.

## 3. Configure linkding

Set the following environment variables:

| Variable                | Description                                            |
| ------------------------| --------------------------------------------------------|
| `LD_DB_ENGINE`           | Set to `d1`                                            |
| `LD_CF_ACCOUNT_ID`       | Your Cloudflare account ID                             |
| `LD_CF_D1_DATABASE_ID`   | The ID of the D1 database created above                |
| `LD_CF_API_TOKEN`        | The API token created above                            |

See the [options reference](/options#ld_cf_account_id) for details.

Everything else (favicons, preview images, HTML snapshots) is still stored on the local filesystem in the `data` folder, independent of the database backend. See the free tier note below for what that means if you don't attach a persistent volume.

## Deploying to Render (free tier)

This repository includes a `render.yaml` [Blueprint](https://render.com/docs/blueprint-spec) for a Render **web service** on the **free** plan (`plan: free`), which prompts for the D1 credentials during setup.

1. Fork or use this repository directly.
2. In the Render dashboard, choose **New > Blueprint** and select the repository.
3. Fill in the `LD_CF_*` and `LD_SUPERUSER_*` values when prompted.

Render automatically sets a `PORT` environment variable that the container will bind to.

:::note
Render's free plan doesn't support persistent disks, so the local `data` folder (favicons, previews, HTML snapshots) resets on every restart or redeploy — your bookmarks/tags/users in D1 are unaffected. Upgrade to a paid plan and add a `disk:` block to `render.yaml` if you need those local files to persist too. The free plan also spins the service down after 15 minutes of inactivity.
:::

## Deploying to Railway (free trial, no volume needed)

This repository includes a `railway.json` config that points Railway at `docker/default.Dockerfile`. It runs fine on Railway's free trial without attaching a volume, since bookmark data lives in D1 rather than on local disk.

1. Create a new Railway project from this repository (or a fork of it).
2. Railway detects `railway.json` and builds the Dockerfile automatically.
3. Under the service's **Variables**, set `LD_DB_ENGINE=d1`, `LD_CF_ACCOUNT_ID`, `LD_CF_D1_DATABASE_ID`, and `LD_CF_API_TOKEN`.
4. Deploy — no volume required.

Railway automatically sets a `PORT` environment variable that the container will bind to.

:::note
Without a volume, the local `data` folder (favicons, previews, HTML snapshots) resets on every restart or redeploy — your bookmarks/tags/users in D1 are unaffected. Railway also deletes any volume created by a trial account 30 days after the trial credits expire, so attaching one wouldn't durably help on the free trial anyway. If you move to a paid plan and want those local files to persist, attach a [volume](https://docs.railway.com/guides/volumes) mounted at `/etc/linkding/data` at that point.
:::
