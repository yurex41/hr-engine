"""
Stage 2 — Job Scraper
Visits each LinkedIn job URL with Playwright and extracts the full job description.
"""
from __future__ import annotations

import json
import time
import logging
import re
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

OUTPUT_FILE = 'jobs_detailed.json'


def scrape_job(page, url: str) -> dict | None:
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=20000)
        time.sleep(2)

        # Expand "Show more" if present
        try:
            page.click('button.show-more-less-html__button', timeout=3000)
            time.sleep(1)
        except Exception:
            pass

        def get_text(selectors: list[str]) -> str:
            for sel in selectors:
                try:
                    el = page.query_selector(sel)
                    if el:
                        t = el.inner_text().strip()
                        if t:
                            return t
                except Exception:
                    pass
            return ''

        title = get_text([
            'h1.top-card-layout__title',
            'h1[class*="job-title"]',
            'h1',
        ])
        company = get_text([
            'a.topcard__org-name-link',
            'a[class*="org-name"]',
            'span[class*="company-name"]',
        ])
        location = get_text([
            'span.topcard__flavor--bullet',
            'span[class*="location"]',
            'span[class*="workplace"]',
        ])
        description = get_text([
            'div.show-more-less-html__markup',
            'div[class*="description__text"]',
            'section.description',
        ])

        if not title and not description:
            logger.warning(f'Could not extract content from {url}')
            return None

        job_id = re.search(r'/view/(\d+)', url)
        return {
            'job_id': job_id.group(1) if job_id else url,
            'url': url,
            'title': title,
            'company': company,
            'location': location,
            'description': description[:8000],  # cap to avoid huge prompts
        }
    except PWTimeout:
        logger.warning(f'Timeout scraping {url}')
        return None
    except Exception as e:
        logger.warning(f'Error scraping {url}: {e}')
        return None


def scrape_jobs(job_refs: list[dict]) -> list[dict]:
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        for i, ref in enumerate(job_refs):
            logger.info(f'Scraping {i+1}/{len(job_refs)}: {ref["url"]}')
            job = scrape_job(page, ref['url'])
            if job:
                results.append(job)
            time.sleep(2)  # polite delay between requests

        browser.close()

    logger.info(f'Successfully scraped {len(results)}/{len(job_refs)} jobs')
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, indent=2)
    return results


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    sample = [{'job_id': '123', 'url': 'https://www.linkedin.com/jobs/view/123/'}]
    scrape_jobs(sample)
