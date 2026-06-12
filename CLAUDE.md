# HR Engine — Job Application Automation Pipeline

An end-to-end automation system that finds relevant LinkedIn job opportunities, scores them against your profile using Claude, generates customized CVs and cover letters, and tracks application status.

## Quick Start

```bash
cd ~/Desktop/hr_engine
export ANTHROPIC_API_KEY=your_key_here
python3 run_pipeline.py
```

### Running from specific stages

```bash
python3 run_pipeline.py --from-filter    # Skip Gmail fetch + scraping; use existing jobs_detailed.json
python3 run_pipeline.py --from-generate  # Skip to CV/cover letter generation; use existing jobs_matched.json
python3 run_pipeline.py --from-track     # Only update tracker
```

## Architecture

### 6-Stage Pipeline

1. **Gmail Reader** (`gmail_reader.py`)
   - Fetches LinkedIn job alert emails from the last 48 hours
   - Extracts job links and metadata
   - Requires: Google OAuth credentials (credentials.json, token.json)

2. **Job Scraper** (`job_scraper.py`)
   - Scrapes full job descriptions using Playwright
   - Saves to `jobs_detailed.json`

3. **Job Filter** (`job_filter.py`)
   - Scores each job 0–100 using Claude API against `preferences.yaml`
   - Filters by score, dealbreakers, preferred industries, locations
   - Saves matched jobs to `jobs_matched.json` and rejected to `jobs_rejected.json`
   - Uses `claude-opus-4-8` model for scoring

4. **CV Generator** (`cv_generator.py`)
   - Generates customized CV + cover letter for each matched job
   - Tailors language to job description and cv_angle from scoring
   - Outputs to `cv_output/` and `cl_output/`
   - Uses templates from `templates/` directory

5. **Cover Letter Generator** (`cover_letter_generator.py`)
   - Generates cover letters as part of CV stage
   - Integrated into cv_generator.py

6. **Job Tracker** (`job_tracker.py`)
   - Maintains `job_tracker.json` with application statuses
   - Generates interactive HTML dashboard (`tracker.html`)
   - Tracks: applied, interviewing, rejected, offer, etc.

### Output Files

```
cv_output/          → Generated CVs (one per matched job)
cl_output/          → Generated cover letters
jobs_detailed.json  → Full job descriptions from scraping
jobs_matched.json   → Jobs passing the filter (with scores)
jobs_rejected.json  → Jobs that didn't match
job_tracker.json    → Application status tracking
tracker.html        → Interactive dashboard (open in browser)
hr_engine.log       → Full execution log
```

## Configuration

### `preferences.yaml`

Controls scoring and filtering:

```yaml
your_profile: |
  [Your background/experience summary]

target_roles:
  - Role 1
  - Role 2

seniority:
  - Senior
  - Manager
  - Director

locations:
  preferred:
    - Warsaw
    - Remote
  excluded:
    - "relocation required"

dealbreaker_keywords:
  - "security clearance"
  - "commission only"

minimum_score: 45           # Jobs below this score are rejected

industries_preferred:
  - Technology
  - Finance

industries_excluded:
  - Gambling
  - Tobacco
```

## Dependencies

```
anthropic              → Claude API for job scoring
google-auth-oauthlib   → Gmail OAuth authentication
google-api-python-client → Gmail API client
playwright             → Web scraping
python-docx            → Generate Word docs (CVs)
pyyaml                 → Parse preferences.yaml
beautifulsoup4         → HTML parsing
```

Install with:
```bash
pip install -r requirements.txt
```

## Setup Requirements

### 1. Google OAuth (Gmail access)

Run once to authenticate:
```bash
python3 gmail_reader.py
```

This creates `credentials.json` and `token.json`. The script will open a browser for Google login.

### 2. Environment Variable

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Or add to `~/.zshrc` / `~/.bash_profile`:
```bash
echo 'export ANTHROPIC_API_KEY=your_key_here' >> ~/.zshrc
```

### 3. CV & Cover Letter Templates

Templates are in `templates/` directory. These are used by cv_generator.py to inject personalized content.

## Key Concepts

### Scoring System

Claude scores each job 0–100 based on:
- Role title match against `target_roles`
- Seniority level match against `seniority`
- Location match against preferred/excluded locations
- Industry alignment
- Dealbreaker keywords (automatic rejection if found)
- Overall fit to candidate profile

Each job gets metadata:
- `score` (0–100)
- `reasoning` (why this score)
- `cv_angle` (which part of your profile to emphasize)
- `dealbreaker` (boolean)

### CV Customization

For each matched job, the CV generator:
1. Reads your base CV template
2. Uses `cv_angle` to customize emphasis
3. Tailors language to job description
4. Generates both Word doc (.docx) and text version

## Logging

Full logs saved to `hr_engine.log`. Console output shows:
- Stage markers (`═══ STAGE X`)
- Per-job progress with emojis (✅ matched, ⬇️ below threshold, ❌ dealbreaker)
- Summary at end

Example:
```
2026-06-10 21:45 [INFO] run_pipeline: ═══════════════════════════════
2026-06-10 21:45 [INFO] run_pipeline: STAGE 3 — Job Filter (Claude scoring)
2026-06-10 21:45 [INFO] job_filter: Scoring 1/15: Digital Marketing Manager @ TechCorp
2026-06-10 21:45 [INFO] job_filter:   ✅ Score 78 — matched
```

## Common Workflows

### Full run (all stages)
```bash
python3 run_pipeline.py
```

### Re-score existing jobs
```bash
python3 run_pipeline.py --from-filter
```

### Regenerate CVs for already-matched jobs
```bash
python3 run_pipeline.py --from-generate
```

### Update tracker after applying to jobs
```bash
# Edit job_tracker.json manually or via tracker.html, then:
python3 run_pipeline.py --from-track
```

## Troubleshooting

- **"ANTHROPIC_API_KEY not set"** → Export the environment variable
- **"jobs_detailed.json not found"** → Run from `gmail` stage or use an earlier checkpoint
- **Gmail auth issues** → Delete `token.json` and re-run `gmail_reader.py`
- **CV generation fails** → Check templates/ directory exists and template files are readable

## File Inventory

| File | Purpose |
|------|---------|
| `run_pipeline.py` | Main orchestrator; entry point |
| `gmail_reader.py` | Stage 1: Fetch LinkedIn alerts |
| `job_scraper.py` | Stage 2: Scrape job descriptions |
| `job_filter.py` | Stage 3: Claude scoring |
| `cv_generator.py` | Stage 4: Generate CVs |
| `cover_letter_generator.py` | Stage 5: Generate cover letters |
| `job_tracker.py` | Stage 6: Track applications |
| `preferences.yaml` | Scoring & filtering rules |
| `credentials.json` | Google OAuth credentials (gitignored) |
| `token.json` | Gmail OAuth token (gitignored) |
| `templates/` | CV & cover letter templates |
| `setup_launchd.sh` | macOS scheduler config (optional) |
