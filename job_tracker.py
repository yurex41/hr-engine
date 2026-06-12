from __future__ import annotations
"""
Stage 6 — Job Tracker
Maintains job_tracker.json: adds new jobs, preserves existing statuses, purges expired ones.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TRACKER_FILE = 'job_tracker.json'
EXPIRY_DAYS = 7


def load_tracker() -> dict:
    if Path(TRACKER_FILE).exists():
        with open(TRACKER_FILE) as f:
            return json.load(f)
    return {}


def save_tracker(tracker: dict):
    with open(TRACKER_FILE, 'w') as f:
        json.dump(tracker, f, indent=2)


def update_tracker(matched_jobs: list[dict]) -> dict:
    tracker = load_tracker()
    now = datetime.now(timezone.utc).isoformat()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=EXPIRY_DAYS)).isoformat()

    # Purge expired unactioned jobs
    expired = [
        jid for jid, entry in tracker.items()
        if entry.get('status') == 'Not Applied' and entry.get('discovered_at', now) < cutoff
    ]
    for jid in expired:
        logger.info(f'Purging expired job: {tracker[jid].get("title")} @ {tracker[jid].get("company")}')
        del tracker[jid]

    # Add new jobs (don't overwrite existing entries)
    added = 0
    for job in matched_jobs:
        jid = job['job_id']
        if jid not in tracker:
            tracker[jid] = {
                'job_id': jid,
                'title': job.get('title', ''),
                'company': job.get('company', ''),
                'location': job.get('location', ''),
                'url': job.get('url', ''),
                'score': job.get('score', 0),
                'reasoning': job.get('reasoning', ''),
                'cv_path': job.get('cv_path', ''),
                'cl_path': job.get('cl_path', ''),
                'status': 'Not Applied',
                'notes': '',
                'discovered_at': now,
                'expires_at': (datetime.now(timezone.utc) + timedelta(days=EXPIRY_DAYS)).isoformat(),
            }
            added += 1

    save_tracker(tracker)
    generate_tracker_html(tracker)
    logger.info(f'Tracker updated: {added} new jobs added, {len(expired)} expired purged, {len(tracker)} total')
    return tracker


def generate_tracker_html(tracker: dict):
    jobs_json = json.dumps(tracker, indent=2)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HR Engine — Job Tracker</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f8fafc; color: #1e293b; }}
  header {{ background: #1e293b; color: white; padding: 20px 32px; display: flex; justify-content: space-between; align-items: center; }}
  header h1 {{ font-size: 18px; font-weight: 600; }}
  header span {{ font-size: 13px; opacity: 0.6; }}
  .stats {{ display: flex; gap: 16px; padding: 24px 32px; }}
  .stat {{ background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px 24px; flex: 1; }}
  .stat .num {{ font-size: 28px; font-weight: 700; }}
  .stat .label {{ font-size: 12px; color: #64748b; margin-top: 2px; }}
  .filters {{ padding: 0 32px 16px; display: flex; gap: 8px; flex-wrap: wrap; }}
  .filter-btn {{ padding: 6px 16px; border: 1px solid #e2e8f0; border-radius: 20px; background: white; cursor: pointer; font-size: 13px; }}
  .filter-btn.active {{ background: #1e293b; color: white; border-color: #1e293b; }}
  .jobs {{ padding: 0 32px 40px; display: flex; flex-direction: column; gap: 12px; }}
  .job-card {{ background: white; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; }}
  .job-header {{ padding: 20px 24px; display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }}
  .job-meta h3 {{ font-size: 15px; font-weight: 600; }}
  .job-meta .sub {{ font-size: 13px; color: #64748b; margin-top: 4px; }}
  .job-meta .reason {{ font-size: 12px; color: #94a3b8; margin-top: 6px; font-style: italic; max-width: 600px; }}
  .job-right {{ display: flex; align-items: center; gap: 12px; flex-shrink: 0; }}
  .score {{ font-size: 22px; font-weight: 700; }}
  .score.high {{ color: #16a34a; }}
  .score.mid {{ color: #d97706; }}
  .score.low {{ color: #dc2626; }}
  .status-select {{ padding: 6px 12px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 13px; background: white; cursor: pointer; }}
  .status-select.not-applied {{ border-color: #e2e8f0; }}
  .status-select.applied {{ border-color: #3b82f6; background: #eff6ff; color: #1d4ed8; }}
  .status-select.interview {{ border-color: #a855f7; background: #faf5ff; color: #7e22ce; }}
  .status-select.offer {{ border-color: #16a34a; background: #f0fdf4; color: #166534; }}
  .status-select.rejected {{ border-color: #dc2626; background: #fef2f2; color: #991b1b; }}
  .job-footer {{ border-top: 1px solid #f1f5f9; padding: 12px 24px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
  .job-footer a {{ font-size: 12px; color: #3b82f6; text-decoration: none; }}
  .job-footer a:hover {{ text-decoration: underline; }}
  .notes-input {{ flex: 1; min-width: 200px; padding: 6px 10px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 12px; }}
  .expires {{ font-size: 11px; color: #94a3b8; margin-left: auto; }}
  .expires.soon {{ color: #dc2626; font-weight: 600; }}
  .empty {{ text-align: center; padding: 60px; color: #94a3b8; }}
</style>
</head>
<body>
<header>
  <h1>HR Engine — Job Tracker</h1>
  <span id="last-updated"></span>
</header>
<div class="stats">
  <div class="stat"><div class="num" id="stat-total">0</div><div class="label">Total Jobs</div></div>
  <div class="stat"><div class="num" id="stat-not-applied">0</div><div class="label">Not Applied</div></div>
  <div class="stat"><div class="num" id="stat-applied">0</div><div class="label">Applied</div></div>
  <div class="stat"><div class="num" id="stat-interview">0</div><div class="label">Interview</div></div>
  <div class="stat"><div class="num" id="stat-offer">0</div><div class="label">Offer</div></div>
</div>
<div class="filters">
  <button class="filter-btn active" onclick="setFilter('all', event)">All</button>
  <button class="filter-btn" onclick="setFilter('Not Applied', event)">Not Applied</button>
  <button class="filter-btn" onclick="setFilter('Applied', event)">Applied</button>
  <button class="filter-btn" onclick="setFilter('Interview', event)">Interview</button>
  <button class="filter-btn" onclick="setFilter('Offer', event)">Offer</button>
  <button class="filter-btn" onclick="setFilter('Rejected', event)">Rejected</button>
</div>
<div class="jobs" id="jobs-container"></div>
<script>
const DATA = {jobs_json};
let allJobs = DATA;
let currentFilter = 'all';
const STORAGE_KEY = 'hr_engine_statuses';
const NOTES_KEY = 'hr_engine_notes';

function getStatuses() {{ try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}'); }} catch {{ return {{}}; }} }}
function getNotes() {{ try {{ return JSON.parse(localStorage.getItem(NOTES_KEY) || '{{}}'); }} catch {{ return {{}}; }} }}
function saveStatus(jobId, status) {{ const s = getStatuses(); s[jobId] = status; localStorage.setItem(STORAGE_KEY, JSON.stringify(s)); }}
function saveNote(jobId, note) {{ const n = getNotes(); n[jobId] = note; localStorage.setItem(NOTES_KEY, JSON.stringify(n)); }}

function setFilter(f, e) {{
  currentFilter = f;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  e.target.classList.add('active');
  renderJobs();
}}

function daysUntil(isoStr) {{
  return Math.ceil((new Date(isoStr) - new Date()) / (1000 * 60 * 60 * 24));
}}

function scoreClass(s) {{
  if (s >= 70) return 'high';
  if (s >= 45) return 'mid';
  return 'low';
}}

function renderJobs() {{
  const container = document.getElementById('jobs-container');
  const statuses = getStatuses();
  const notes = getNotes();
  const jobs = Object.values(allJobs).map(j => ({{
    ...j,
    status: statuses[j.job_id] || j.status || 'Not Applied',
    notes: notes[j.job_id] || j.notes || '',
  }}));
  const filtered = currentFilter === 'all' ? jobs : jobs.filter(j => j.status === currentFilter);
  filtered.sort((a, b) => (b.score || 0) - (a.score || 0));
  document.getElementById('stat-total').textContent = jobs.length;
  document.getElementById('stat-not-applied').textContent = jobs.filter(j => j.status === 'Not Applied').length;
  document.getElementById('stat-applied').textContent = jobs.filter(j => j.status === 'Applied').length;
  document.getElementById('stat-interview').textContent = jobs.filter(j => j.status === 'Interview').length;
  document.getElementById('stat-offer').textContent = jobs.filter(j => j.status === 'Offer').length;
  document.getElementById('last-updated').textContent = jobs.length + ' jobs';
  if (filtered.length === 0) {{ container.innerHTML = '<div class="empty">Bu kategoride iş yok.</div>'; return; }}
  container.innerHTML = filtered.map(job => {{
    const days = daysUntil(job.expires_at);
    const expClass = days <= 2 ? 'soon' : '';
    const statusClass = job.status.toLowerCase().replace(' ', '-');
    return `
    <div class="job-card">
      <div class="job-header">
        <div class="job-meta">
          <h3>${{job.title}}</h3>
          <div class="sub">${{job.company}} · ${{job.location}}</div>
          ${{job.reasoning ? `<div class="reason">${{job.reasoning}}</div>` : ''}}
        </div>
        <div class="job-right">
          <div class="score ${{scoreClass(job.score)}}">${{job.score || '—'}}</div>
          <select class="status-select ${{statusClass}}" onchange="onStatusChange('${{job.job_id}}', this)">
            ${{['Not Applied','Applied','Interview','Offer','Rejected'].map(s => `<option${{s === job.status ? ' selected' : ''}}>${{s}}</option>`).join('')}}
          </select>
        </div>
      </div>
      <div class="job-footer">
        <a href="${{job.url}}" target="_blank">LinkedIn'de Gör</a>
        ${{job.cv_path ? `<a href="${{job.cv_path}}">CV'yi Aç</a>` : ''}}
        <input class="notes-input" placeholder="Not ekle..." value="${{job.notes}}" onblur="saveNote('${{job.job_id}}', this.value)" />
        <span class="expires ${{expClass}}">${{days}}g kaldı</span>
      </div>
    </div>`;
  }}).join('');
}}

function onStatusChange(jobId, select) {{
  saveStatus(jobId, select.value);
  select.className = `status-select ${{select.value.toLowerCase().replace(' ', '-')}}`;
  renderJobs();
}}

renderJobs();
</script>
</body>
</html>"""
    with open('tracker.html', 'w') as f:
        f.write(html)
    logger.info('tracker.html updated')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    with open('jobs_matched.json') as f:
        jobs = json.load(f)
    update_tracker(jobs)
