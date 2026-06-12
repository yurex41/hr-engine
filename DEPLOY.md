# HR Engine — Web Deployment Guide

## Architecture decision: Render (recommended) vs. $5 VPS

**Recommendation: Render, Docker runtime, with a persistent disk.**

Why, in plain terms:

| | Render | $5 VPS (Hetzner/DigitalOcean) |
|---|---|---|
| HTTPS / domain | Automatic (`*.onrender.com`) | You run Caddy/nginx + DNS yourself |
| Deploys | `git push` → auto build & deploy | SSH in, `docker compose up -d --build` |
| Secrets | Dashboard env vars | `.env` file you protect yourself |
| OS patching, reboots | Render's problem | Your problem |
| Cost | ~$25/mo (Standard, 2 GB RAM) + $0.25/mo disk | ~$5–8/mo |
| RAM for Chromium | Pick plan size | 2 GB VPS is fine |

The pipeline runs **Playwright + Chromium**, which needs ~1 GB+ of RAM while
scraping. That rules out free/hobby tiers (512 MB → out-of-memory kills).
So the real choice is "Render Standard at ~$25/mo, zero ops knowledge needed"
vs. "a 2 GB VPS at ~$5/mo, with ~30 minutes of one-time setup".

- **You want it live today and never think about servers** → Render.
  Everything below works with the included `render.yaml`.
- **You care about the $20/mo difference** → VPS. The included
  `docker-compose.yml` + `Caddyfile` make it nearly as easy: Caddy gets the
  HTTPS certificate automatically, so there is no nginx/certbot fiddling.

Both paths use the **same Docker image**, so you can start on Render and move
to a VPS later without changing any code.

> ⚠️ **One honest caveat:** LinkedIn aggressively rate-limits datacenter IPs.
> Scraping (stage 2) may work less reliably from a cloud server than from your
> home Mac. If scraping fails in the cloud, a common pattern is: run stages 1–2
> locally on a schedule, sync `jobs_detailed.json` up, and use the web app for
> stages 3–6 (`From Filter` button) plus the dashboard/downloads/editor.

---

## How the web app works

- `app.py` (Flask) wraps the existing CLI untouched — it runs
  `python3 run_pipeline.py [--from-…]` as a subprocess and streams its stdout
  to the browser over **Server-Sent Events**.
- **Multi-user:** logins are defined in `APP_USERS` (`"yurek:pw1,alice:pw2"`).
  Each user gets an isolated workspace at `DATA_DIR/users/<name>/` with their
  own Gmail token, `preferences.yaml`, CV/CL templates (uploadable in the UI),
  job data and generated documents. The pipeline runs inside that workspace,
  so users never see each other's data. One pipeline run at a time
  server-wide (Chromium is memory-hungry); the UI shows who's running.
- Every route requires **HTTP Basic auth**. The browser prompts once and
  remembers it; always use HTTPS (both deployment paths provide it).
- All mutable state lives in `DATA_DIR` (`/data` in Docker), a **persistent
  volume** — it survives redeploys. On first boot with existing single-user
  data, everything is migrated automatically into the **first** user listed
  in `APP_USERS` — so put yourself first.
- Secrets (`ANTHROPIC_API_KEY`, `GOOGLE_CLIENT_JSON`, `APP_PASSWORD`) are
  injected as **environment variables**, never baked into the image
  (see `.dockerignore`).

### Google OAuth in a web context

The terminal flow (`InstalledAppFlow.run_local_server`) can't work on a
server — there's no browser there. Instead:

1. You click **🔑 Connect Google** in the UI → `/auth/google` redirects you to
   Google's consent screen (requesting `gmail.readonly`, `access_type=offline`
   so we get a **refresh token**).
2. Google redirects back to `https://<your-app>/oauth2callback`; the server
   exchanges the code for tokens and writes `token.json` (mode 600) to the
   persistent disk.
3. From then on the pipeline runs unattended: `gmail_reader.py` reads
   `token.json` and silently refreshes it when it expires. If the token is
   missing, it now raises a clear error telling you to click Connect Google
   (instead of hanging trying to open a browser on the server).

This requires a **"Web application"** OAuth client (your current
`credentials.json` is a "Desktop" client, which only allows localhost
redirects). Creating one takes 2 minutes — see step 1 below.

---

## Path A — Deploy to Render (recommended)

### 1. Create a Web OAuth client (one-time, ~2 min)

1. [Google Cloud Console](https://console.cloud.google.com) → same project as
   your current credentials → **APIs & Services → Credentials**.
2. **Create Credentials → OAuth client ID → Web application**.
3. Authorized redirect URI: `https://<your-service-name>.onrender.com/oauth2callback`
   (you can add/fix this after Render assigns the URL).
4. Download the JSON. You'll paste its contents into an env var in step 4.

### 2. Push the code to a **private** GitHub repo

```bash
cd ~/Desktop/hr_engine
git init
printf 'token.json\ncredentials.json\n.env\n*.log\njobs_*.json\njob_tracker.json\ntracker.html\ncv_output/\ncl_output/\ndata/\n__pycache__/\n.DS_Store\npreferences.yaml.bak\n' > .gitignore
git add . && git commit -m "HR Engine web app"
# create a PRIVATE repo on github.com, then:
git remote add origin git@github.com:YOURUSER/hr-engine.git
git push -u origin main
```

### 3. Create the service

Render dashboard → **New + → Blueprint** → pick your repo. Render reads
`render.yaml` (Docker build, `/data` disk, Standard plan).

### 4. Set the secrets (Render dashboard → Environment)

| Variable | Value |
|---|---|
| `APP_USERS` | `yurek:pw1,alice:pw2,…` — yourself first; long random passwords (`openssl rand -base64 18` per person) |
| `ANTHROPIC_API_KEY` | your `sk-ant-…` key (shared by all users by default) |
| `ANTHROPIC_API_KEY_<NAME>` | *optional* per-user key so a friend pays for their own usage |
| `GOOGLE_CLIENT_JSON` | entire contents of the Web-client JSON from step 1, one line |
| `PUBLIC_BASE_URL` | `https://<your-service>.onrender.com` (no trailing slash) |

### 5. First-run setup (you, and each friend, separately)

1. Open `https://<your-service>.onrender.com` → browser asks for your
   username/password from `APP_USERS`.
2. Click **🔑 Connect Google** and approve the consent screen with **your own**
   Google account → badge turns `google: connected`.
3. Fill in **preferences.yaml** in the editor (new users get a placeholder
   template), Save.
4. Upload your own **CV and cover letter `.docx` templates** in the Templates
   section (new users start with the seed templates).
5. Click **▶ Run All** and watch the live log.

---

## Path B — Deploy to a $5 VPS

Works on any Ubuntu 22.04+ box (Hetzner CX22 ~€4/mo with 4 GB RAM is ideal).

```bash
# 1. On the VPS: install Docker
curl -fsSL https://get.docker.com | sh

# 2. Point a DNS A record (e.g. hr.yourdomain.com) at the VPS IP,
#    and put that hostname in Caddyfile (replace hr.example.com).

# 3. Copy the project up (from your Mac):
rsync -av --exclude-from=.dockerignore ~/Desktop/hr_engine/ root@VPS_IP:/opt/hr_engine/

# 4. On the VPS: configure secrets and start
cd /opt/hr_engine
cp .env.example .env && nano .env        # fill all values; PUBLIC_BASE_URL=https://hr.yourdomain.com
chmod 600 .env
docker compose up -d --build
```

Add `https://hr.yourdomain.com/oauth2callback` as an authorized redirect URI
on your Web OAuth client, then do "First-run setup" exactly as in Path A.

Updates later: edit code locally → `rsync` again → `docker compose up -d --build`.

---

## Adding friends (the Google part — read this!)

The app side is trivial: add `friend:password` to `APP_USERS`, redeploy, send
them the URL + their password. The constraints all come from Google, because
`gmail.readonly` is a **restricted scope**:

1. **Add each friend as a test user.** Google Cloud Console → APIs & Services
   → OAuth consent screen → Audience → Test users → add their Gmail address.
   Until you do this, Google will refuse their consent screen entirely.
   Limit: 100 test users.
2. **Tokens expire every 7 days** while your OAuth app is in "Testing" mode.
   Everyone (including you) has to click **Connect Google** again weekly —
   it's two clicks, and the UI badge turns red (`google: not connected`) when
   it's needed. Getting rid of this requires Google's restricted-scope
   verification (a paid third-party security audit, meant for real products) —
   not worth it for a friends-only tool.
3. **Costs:** every run spends Claude API credits on scoring + CV generation.
   By default that's all on your `ANTHROPIC_API_KEY`. If a friend gets heavy
   with it, give them their own key via `ANTHROPIC_API_KEY_<NAME>` — they can
   create one at console.anthropic.com.

What friends can and can't do: each user only ever sees their own workspace
(their Gmail-derived jobs, their preferences, their documents). There is no
admin role — nobody can see anyone else's data, including you (except by
opening the files on the server disk directly).

---

## Local test before deploying (optional but recommended)

```bash
cd ~/Desktop/hr_engine
pip3 install -r requirements.txt
export APP_USERS="yurek:test" ANTHROPIC_API_KEY=sk-ant-...
python3 app.py        # → http://localhost:8000  (login: yurek / test)
```

Locally, `DATA_DIR` defaults to the project folder itself. On first start your
existing `token.json`, preferences, templates, tracker and outputs are copied
into `users/yurek/` (the original files are left in place untouched).

---

## Deployment checklist (Render path)

- [ ] Google Cloud: create **Web application** OAuth client; add
      `https://<app>.onrender.com/oauth2callback` redirect URI; download JSON
- [ ] `git init` + push to **private** GitHub repo (verify `token.json`,
      `credentials.json` are NOT in the repo — the `.gitignore` above covers it)
- [ ] Render → New → Blueprint → select repo
- [ ] Set env vars: `APP_USERS` (yourself first!), `ANTHROPIC_API_KEY`,
      `GOOGLE_CLIENT_JSON`, `PUBLIC_BASE_URL`
- [ ] Google consent screen → add yourself + each friend as **test users**
- [ ] Wait for the build (first one ~5–10 min: pulls the Playwright image)
- [ ] Open the URL, log in with your username/password
- [ ] Click **Connect Google** → consent → badge shows `connected`
- [ ] Fill in `preferences.yaml`; upload your CV/CL `.docx` templates
- [ ] **▶ Run All** → watch live logs → tracker renders → download a CV
- [ ] Send each friend: the URL, their password, and the first-run steps above

## Security notes

- HTTPS everywhere (Render/Caddy provide it) — Basic auth credentials are
  base64, so they're only safe over TLS.
- One password per person (`APP_USERS`); removing an entry and redeploying
  instantly locks that person out without affecting anyone else.
- Workspaces are isolated per user; there is no cross-user data access.
- `gmail.readonly` scope only — the app can never send or delete email.
- Secrets live in env vars; the image and the git repo contain none of:
  `token.json`, `credentials.json`, API keys, generated documents.
- `token.json` is written with `0600` permissions on the persistent disk.
- Downloads are served via `send_from_directory`, which blocks path traversal.
