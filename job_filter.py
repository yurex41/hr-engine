from __future__ import annotations
"""
Stage 3 — Job Filter
Scores each job 0-100 using Gemini against your preferences.yaml profile.
"""

import os
import json
import logging
import yaml
import anthropic

logger = logging.getLogger(__name__)

MATCHED_FILE = 'jobs_matched.json'
REJECTED_FILE = 'jobs_rejected.json'


def load_preferences() -> dict:
    with open('preferences.yaml') as f:
        return yaml.safe_load(f)


def score_job(client, prefs: dict, job: dict) -> dict:
    prompt = f"""You are an expert recruiter scoring a job against a candidate's profile.

CANDIDATE PROFILE:
{prefs['your_profile']}

Target roles: {', '.join(prefs.get('target_roles', []))}
Preferred seniority: {', '.join(prefs.get('seniority', []))}
Preferred locations: {', '.join(prefs.get('locations', {}).get('preferred', []))}
Excluded locations: {', '.join(prefs.get('locations', {}).get('excluded', []))}
Dealbreaker keywords: {', '.join(prefs.get('dealbreaker_keywords', []))}
Preferred industries: {', '.join(prefs.get('industries_preferred', []))}
Excluded industries: {', '.join(prefs.get('industries_excluded', []))}

JOB TO SCORE:
Title: {job.get('title', 'Unknown')}
Company: {job.get('company', 'Unknown')}
Location: {job.get('location', 'Unknown')}
Description:
{job.get('description', '')[:3000]}

Return ONLY valid JSON (no markdown):
{{
  "score": <integer 0-100>,
  "reasoning": "<2-3 sentences explaining the score>",
  "cv_angle": "<which part of candidate profile to emphasise for this role>",
  "dealbreaker": <true if any dealbreaker keyword found, false otherwise>,
  "dealbreaker_reason": "<reason if dealbreaker, else empty string>"
}}"""

    response = client.messages.create(
        model='claude-opus-4-8',
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.content[0].text.strip()
    # Strip markdown fences if present
    if text.startswith('```'):
        text = text.split('```')[1]
        if text.startswith('json'):
            text = text[4:]
    return json.loads(text.strip())


def filter_jobs(jobs: list[dict]) -> tuple[list[dict], list[dict]]:
    prefs = load_preferences()
    min_score = prefs.get('minimum_score', 42)

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from environment

    matched = []
    rejected = []

    for i, job in enumerate(jobs):
        logger.info(f'Scoring {i+1}/{len(jobs)}: {job.get("title")} @ {job.get("company")}')
        try:
            result = score_job(client, prefs, job)
            job['score'] = result['score']
            job['reasoning'] = result['reasoning']
            job['cv_angle'] = result.get('cv_angle', '')
            job['dealbreaker'] = result.get('dealbreaker', False)
            job['dealbreaker_reason'] = result.get('dealbreaker_reason', '')

            if result.get('dealbreaker'):
                logger.info(f'  ❌ Dealbreaker: {result["dealbreaker_reason"]}')
                rejected.append(job)
            elif result['score'] >= min_score:
                logger.info(f'  ✅ Score {result["score"]} — matched')
                matched.append(job)
            else:
                logger.info(f'  ⬇️  Score {result["score"]} — below threshold {min_score}')
                rejected.append(job)
        except Exception as e:
            logger.error(f'  Error scoring job {job.get("job_id")}: {e}')
            rejected.append(job)

    matched.sort(key=lambda j: j['score'], reverse=True)

    with open(MATCHED_FILE, 'w') as f:
        json.dump(matched, f, indent=2)
    with open(REJECTED_FILE, 'w') as f:
        json.dump(rejected, f, indent=2)

    logger.info(f'Matched: {len(matched)} | Rejected: {len(rejected)}')
    return matched, rejected


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    with open('jobs_detailed.json') as f:
        jobs = json.load(f)
    filter_jobs(jobs)
