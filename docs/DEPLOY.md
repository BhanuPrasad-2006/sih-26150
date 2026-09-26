# Putting the demo online (frontend + backend)

The backend serves the frontend, so **one web service is the whole site**. This guide uses Render because it builds
straight from the `Dockerfile`. Any host that runs a Docker container with a public HTTPS URL works the same way.

> **This is a demo, not a forensic workstation.** The tool was designed for local use (see `docs/SECURITY.md`). A public
> copy is fine for judges to click through, but do not put real evidence or real case data on it.

## Before you start

1. **Use a separate database.** Create a second, empty Supabase (or any Postgres) project for the demo and copy its
   connection string. If you reuse your real database, the public site will share your real examiner password, cases and
   audit log.
2. **Know the free-tier limits.** On Render's free plan the disk is wiped on every restart or redeploy, and the service
   sleeps when idle (the first request after a sleep takes about a minute). Cases and signing keys in `/data` are lost
   with it. The database survives, so the login survives, but exported videos and reports do not. A paid plan with a
   disk mounted at `/data` fixes that.
3. **Memory.** The free plan has 512 MB. The face and object models may not fit while a scan runs; if the service is
   killed, use a plan with more memory.

## Steps

1. Merge this branch into `main` (only when you are happy with it).
2. On render.com, sign in with GitHub, choose **New → Blueprint**, and pick the `sih-26150` repository. Render reads
   `render.yaml`.
3. When it asks for the two secret values, enter:
   - `DATABASE_URL` – the demo database connection string.
   - `SIH_ALLOWED_HOSTS` – your service hostname, for example `sih-forensic-demo.onrender.com` (no `https://`, no path).
     If the name you chose is taken, Render adds a suffix; use the hostname shown on the service page and update the
     variable afterwards.
4. Wait for the build. Open `https://<your-service>.onrender.com`.
5. **Immediately create the examiner password.** On a fresh database the first visitor to the setup screen becomes the
   owner. Do this yourself before sharing the link.
6. Load the generated test pack (`docs/TEST_PACK.md`) so judges have something to scan. Keep uploads small.

## If something goes wrong

| Symptom | Cause |
|---|---|
| "Host not allowed" | `SIH_ALLOWED_HOSTS` does not match the URL in the address bar exactly. |
| Login works but you are logged out at once | `FORWARDED_ALLOW_IPS` missing, so the cookie is not marked Secure behind the HTTPS proxy. |
| Build fails at `pip install` | Check the build log; the Dockerfile has not been built in the development environment. |
| Service restarts during a scan | Out of memory (see above). |

## What stays true

The same guarantees as the local tool apply (read-only evidence, hashes, audit log), but a public server adds risks the
local tool does not have: anyone can reach the login page, and the host operator can see what is uploaded. That is why
this guide is for a demo only.
