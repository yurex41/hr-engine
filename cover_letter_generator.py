from __future__ import annotations
"""
Stage 5 — Cover Letter Generator
Writes a 4-paragraph cover letter per job using Gemini and injects into your DOCX template.
"""

import os
import json
import logging
from pathlib import Path
import anthropic
from docx import Document

logger = logging.getLogger(__name__)

TEMPLATE_PATH = 'templates/CL_template.docx'
OUTPUT_DIR = Path('cl_output')
OUTPUT_DIR.mkdir(exist_ok=True)


def generate_cover_letter(client, job: dict) -> str:
    prompt = f"""Write a professional cover letter for this job. Use exactly 4 paragraphs:

1. Profile intro — who I am and why I'm right for THIS specific role (paraphrased, not generic)
2. Recent relevant experience — one concrete achievement directly relevant to this job
3. Secondary strength — a complementary skill or experience that adds value
4. What excites me about this specific company and opportunity

JOB:
Title: {job.get('title')}
Company: {job.get('company')}
Location: {job.get('location')}
Description: {job.get('description', '')[:2000]}

CV Angle: {job.get('cv_angle', '')}

RULES:
- First person, professional but warm tone
- No fabricated skills or credentials
- Specific to this company — mention something real about them if possible
- Each paragraph 3-4 sentences max
- No salutation or sign-off (template handles that)
- Return only the 4 paragraphs as plain text, separated by blank lines"""

    response = client.messages.create(
        model='claude-opus-4-8',
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


def inject_into_docx(template_path: str, body_text: str, output_path: str):
    doc = Document(template_path)
    placeholder = '<<COVER_LETTER_BODY>>'

    for para in doc.paragraphs:
        if placeholder in para.text:
            # Clear existing runs
            for run in para.runs:
                run.text = ''
            # Write the cover letter body into this paragraph
            para.runs[0].text = body_text if para.runs else ''
            # If no runs, add one
            if not para.runs:
                para.add_run(body_text)
            break

    doc.save(output_path)


def generate_cover_letters(matched_jobs: list[dict]) -> list[dict]:
    if not Path(TEMPLATE_PATH).exists():
        logger.warning(f'Cover letter template not found at {TEMPLATE_PATH}. Skipping.')
        logger.warning('Place your cover letter as templates/CL_template.docx with <<COVER_LETTER_BODY>> placeholder.')
        return matched_jobs

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from environment

    for job in matched_jobs:
        company_slug = ''.join(c if c.isalnum() else '_' for c in job.get('company', 'company'))
        title_slug = ''.join(c if c.isalnum() else '_' for c in job.get('title', 'role'))
        output_path = str(OUTPUT_DIR / f"CL_{company_slug}_{title_slug}.docx")

        logger.info(f'Writing cover letter for {job.get("title")} @ {job.get("company")}')
        try:
            body = generate_cover_letter(client, job)
            inject_into_docx(TEMPLATE_PATH, body, output_path)
            job['cl_path'] = output_path
            logger.info(f'  ✅ Saved: {output_path}')
        except Exception as e:
            logger.error(f'  ❌ Cover letter failed: {e}')

    return matched_jobs


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    with open('jobs_matched.json') as f:
        jobs = json.load(f)
    generate_cover_letters(jobs)
