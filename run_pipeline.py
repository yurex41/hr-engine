from __future__ import annotations
"""
Main orchestrator — runs all pipeline stages in sequence.

Usage:
  python run_pipeline.py                  # Full run (Gmail → scrape → score → generate → track)
  python run_pipeline.py --from-filter    # Skip Gmail + scraping, use existing jobs_detailed.json
  python run_pipeline.py --from-generate  # Skip to generation, use existing jobs_matched.json
  python run_pipeline.py --from-track     # Skip to tracker update only
"""

import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path

# ── Logging setup ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('hr_engine.log'),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger('run_pipeline')

EXPIRY_DAYS = 7


def check_env():
    key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not key:
        logger.error('ANTHROPIC_API_KEY environment variable not set.')
        logger.error('Run: export ANTHROPIC_API_KEY=your_key_here')
        sys.exit(1)


def stage_gmail() -> list[dict]:
    from gmail_reader import fetch_jobs
    logger.info('═' * 50)
    logger.info('STAGE 1 — Gmail Reader')
    jobs = fetch_jobs(hours_back=48)
    if not jobs:
        logger.warning('No new LinkedIn job alert emails found in the last 48 hours.')
    return jobs


def stage_scrape(job_refs: list[dict]) -> list[dict]:
    from job_scraper import scrape_jobs
    logger.info('═' * 50)
    logger.info('STAGE 2 — Job Scraper')
    return scrape_jobs(job_refs)


def stage_filter(detailed_jobs: list[dict]) -> tuple[list[dict], list[dict]]:
    from job_filter import filter_jobs
    logger.info('═' * 50)
    logger.info('STAGE 3 — Job Filter (Claude scoring)')
    return filter_jobs(detailed_jobs)


def stage_generate(matched_jobs: list[dict]) -> list[dict]:
    from cv_generator import generate_cvs
    logger.info('═' * 50)
    logger.info('STAGE 4 — CV Generator')
    matched_jobs = generate_cvs(matched_jobs)
    # Save updated matched jobs (now with cv_path and cl_path)
    with open('jobs_matched.json', 'w') as f:
        json.dump(matched_jobs, f, indent=2)
    return matched_jobs


def stage_track(matched_jobs: list[dict]) -> dict:
    from job_tracker import update_tracker
    logger.info('═' * 50)
    logger.info('STAGE 6 — Job Tracker')
    return update_tracker(matched_jobs)


def main():
    check_env()

    args = sys.argv[1:]
    start_from = 'gmail'
    if '--from-filter' in args:
        start_from = 'filter'
    elif '--from-generate' in args:
        start_from = 'generate'
    elif '--from-track' in args:
        start_from = 'track'

    logger.info('═' * 50)
    logger.info(f'HR Engine starting — {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    logger.info(f'Starting from stage: {start_from}')

    # ── Stage 1 & 2: Gmail + Scraping ─────────────────────────────────────
    if start_from == 'gmail':
        job_refs = stage_gmail()
        if not job_refs:
            logger.info('Nothing to process. Exiting.')
            return
        detailed_jobs = stage_scrape(job_refs)
        if not detailed_jobs:
            logger.warning('No jobs successfully scraped. Exiting.')
            return
    else:
        logger.info('Loading existing jobs_detailed.json...')
        if not Path('jobs_detailed.json').exists():
            logger.error('jobs_detailed.json not found. Run without --from-filter first.')
            sys.exit(1)
        with open('jobs_detailed.json') as f:
            detailed_jobs = json.load(f)

    # ── Stage 3: Scoring ───────────────────────────────────────────────────
    if start_from in ('gmail', 'filter'):
        matched_jobs, rejected_jobs = stage_filter(detailed_jobs)
        if not matched_jobs:
            logger.info('No jobs met the minimum score threshold. Exiting.')
            return
    else:
        logger.info('Loading existing jobs_matched.json...')
        if not Path('jobs_matched.json').exists():
            logger.error('jobs_matched.json not found.')
            sys.exit(1)
        with open('jobs_matched.json') as f:
            matched_jobs = json.load(f)

    # ── Stage 4 & 5: CV + Cover Letter Generation ─────────────────────────
    if start_from in ('gmail', 'filter', 'generate'):
        matched_jobs = stage_generate(matched_jobs)

    # ── Stage 6: Tracker ───────────────────────────────────────────────────
    tracker = stage_track(matched_jobs)

    # ── Summary ────────────────────────────────────────────────────────────
    logger.info('═' * 50)
    logger.info('✅ Pipeline complete')
    logger.info(f'   Matched jobs this run : {len(matched_jobs)}')
    logger.info(f'   Total tracked jobs    : {len(tracker)}')
    logger.info(f'   CVs generated in      : cv_output/')
    logger.info(f'   Cover letters in      : cl_output/')
    logger.info(f'   Open tracker.html to review and update statuses')


if __name__ == '__main__':
    main()
