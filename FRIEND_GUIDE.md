# HR Engine — Getting Started (for invited users)

You've been given access to HR Engine: it reads your LinkedIn job alert
emails, scores each job against your profile with AI, generates a tailored
CV + cover letter for every good match, and tracks your applications.

Your data is private — each user has an isolated workspace. Nobody else
(including the person who invited you) can see your emails, profile, or
documents through the app.

## What you received

- **URL** — e.g. `https://hr-engine-xxxx.onrender.com`
- **Username and password**

## One-time setup (~10 minutes)

### 1. Log in
Open the URL. Your **browser** shows a username/password popup (not a web
page) — enter the credentials you were sent.

### 2. Connect your Gmail
Click **🔑 Connect Google**. Sign in with your own Google account.

> ⚠️ Google will warn: *"Google hasn't verified this app."* This is normal
> for small private tools — click **Continue**. The app gets **read-only**
> access to Gmail: it can never send, delete, or modify anything.

You'll return to the dashboard with the badge showing `google: connected`.

### 3. Make sure you get LinkedIn job alert emails
The pipeline works by reading emails from `jobalerts-noreply@linkedin.com`.
On LinkedIn: search the jobs you want → toggle **job alert** on → in alert
settings, enable **email** notifications. No alert emails = nothing to find.

### 4. Fill in your profile (preferences.yaml)
Scroll to the **preferences.yaml** editor. Replace every `REPLACE ME`:

- `your_profile` — a few sentences about your background and strengths
- `target_roles` — job titles you want
- `seniority`, `locations`, `dealbreaker_keywords`, industries
- `minimum_score` — jobs scored below this (0–100) are rejected; 45 is a
  sensible start

Click **💾 Save** (it validates the YAML and keeps a backup).

### 5. Upload your CV and cover letter templates
In **CV & Cover Letter Templates**: pick "CV template", choose your own
`.docx` CV, click **⬆ Upload**. Repeat for the cover letter. The pipeline
keeps your document's formatting and tailors the content per job. (If you
skip this, you'll get documents in the default template's layout.)

## Running it

Click **▶ Run All** and watch the live log:

1. fetches your LinkedIn alert emails (last 48 h)
2. scrapes each job description
3. AI-scores every job 0–100 against your profile (✅ matched / ⬇️ below
   threshold / ❌ dealbreaker)
4. generates a tailored CV + cover letter per matched job
5. updates your tracker dashboard

First run takes several minutes. Then:

- **Job Tracker** section — your matched jobs, scores, and application statuses
- **Generated Files** section — download each CV / cover letter

The other buttons re-run parts only: **From Filter** re-scores already-fetched
jobs (e.g. after editing preferences), **From Generate** regenerates documents,
**From Track** refreshes the tracker.

## Good to know

- **Every ~7 days** the `google:` badge turns red — Google expires access to
  unverified apps weekly. Just click **Connect Google** again (two clicks).
- **"Server is busy: <name>'s pipeline is running"** — only one person can
  run at a time. Wait a few minutes and retry.
- Run it every day or two; it only looks at alert emails from the last 48 hours.
- Each run uses paid AI credits — be reasonable with re-runs.
