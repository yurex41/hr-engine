from __future__ import annotations
"""
Stage 4 — CV Generator
Generates tailored CV content per job using Gemini and injects it into your DOCX template.
"""

import os
import json
import logging
import copy
from pathlib import Path
import anthropic
from docx import Document
from docx.shared import Pt

logger = logging.getLogger(__name__)

TEMPLATE_PATH = 'templates/CV_template.docx'
OUTPUT_DIR = Path('cv_output')
OUTPUT_DIR.mkdir(exist_ok=True)


def generate_cv_content(client, job: dict) -> dict:
    prompt = f"""You are a CV writer helping tailor a CV for a specific job.

JOB:
Title: {job.get('title')}
Company: {job.get('company')}
Location: {job.get('location')}
Description: {job.get('description', '')[:2000]}

CV Angle suggested by scorer: {job.get('cv_angle', '')}

Generate tailored CV content. Return ONLY valid JSON (no markdown):
{{
  "professional_title": "<tailored job title for the top of CV, matching this role>",
  "profile_summary": "<3-4 sentence professional summary tailored to this specific role and company>",
  "key_achievements": [
    "<achievement 1 — quantified, relevant to this role>",
    "<achievement 2 — quantified, relevant to this role>",
    "<achievement 3 — quantified, relevant to this role>"
  ]
}}

IMPORTANT: Only use real experience from the CV angle provided. Do not fabricate skills or credentials."""

    response = client.messages.create(
        model='claude-opus-4-8',
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.content[0].text.strip()
    if text.startswith('```'):
        text = text.split('```')[1]
        if text.startswith('json'):
            text = text[4:]
    return json.loads(text.strip())


def inject_into_docx(template_path: str, content: dict, output_path: str):
    """Replace placeholder text in the DOCX template with generated content."""
    doc = Document(template_path)

    replacements = {
        '<<PROFESSIONAL_TITLE>>': content.get('professional_title', ''),
        '<<PROFILE_SUMMARY>>': content.get('profile_summary', ''),
        '<<KEY_ACHIEVEMENT_1>>': content['key_achievements'][0] if len(content.get('key_achievements', [])) > 0 else '',
        '<<KEY_ACHIEVEMENT_2>>': content['key_achievements'][1] if len(content.get('key_achievements', [])) > 1 else '',
        '<<KEY_ACHIEVEMENT_3>>': content['key_achievements'][2] if len(content.get('key_achievements', [])) > 2 else '',
    }

    for para in doc.paragraphs:
        for key, value in replacements.items():
            if key in para.text:
                for run in para.runs:
                    if key in run.text:
                        run.text = run.text.replace(key, value)

    # Also check tables
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    for key, value in replacements.items():
                        if key in para.text:
                            for run in para.runs:
                                if key in run.text:
                                    run.text = run.text.replace(key, value)

    doc.save(output_path)


def generate_cvs(matched_jobs: list[dict]) -> list[dict]:
    if not Path(TEMPLATE_PATH).exists():
        logger.warning(f'CV template not found at {TEMPLATE_PATH}. Skipping CV generation.')
        logger.warning('Place your CV as templates/CV_template.docx with placeholders:')
        logger.warning('  <<PROFESSIONAL_TITLE>>, <<PROFILE_SUMMARY>>, <<KEY_ACHIEVEMENT_1>>, etc.')
        return matched_jobs

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from environment

    for job in matched_jobs:
        company_slug = ''.join(c if c.isalnum() else '_' for c in job.get('company', 'company'))
        title_slug = ''.join(c if c.isalnum() else '_' for c in job.get('title', 'role'))
        output_path = str(OUTPUT_DIR / f"CV_{company_slug}_{title_slug}.docx")

        logger.info(f'Generating CV for {job.get("title")} @ {job.get("company")}')
        try:
            content = generate_cv_content(client, job)
            inject_into_docx(TEMPLATE_PATH, content, output_path)
            job['cv_path'] = output_path
            logger.info(f'  ✅ Saved: {output_path}')
        except Exception as e:
            logger.error(f'  ❌ CV generation failed: {e}')

    return matched_jobs


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    with open('jobs_matched.json') as f:
        jobs = json.load(f)
    generate_cvs(jobs)
