from __future__ import annotations
"""
Stage 1 — Gmail Reader
Fetches LinkedIn job alert emails from the last 48 hours and extracts job URLs.
"""

import os
import sys
import base64
import re
import json
import logging
from datetime import datetime, timedelta, timezone
from email import message_from_bytes

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
TOKEN_FILE = 'token.json'
CREDENTIALS_FILE = 'credentials.json'


def get_gmail_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif os.environ.get('HR_ENGINE_WEB') or not sys.stdin.isatty():
            # Running under the web server: the browser-based OAuth flow in
            # app.py is responsible for creating token.json.
            raise RuntimeError(
                'No valid Gmail token. Open the web UI and click '
                '"Connect Google" to authenticate, then re-run the pipeline.')
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)


def extract_job_urls(text: str) -> list[str]:
    """Extract LinkedIn job URLs from email body text."""
    patterns = [
        r'https://www\.linkedin\.com/jobs/view/(\d+)',
        r'https://www\.linkedin\.com/comm/jobs/view/(\d+)',
    ]
    job_ids = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            job_ids.add(match.group(1))
    return [f'https://www.linkedin.com/jobs/view/{jid}/' for jid in job_ids]


def decode_body(part) -> str:
    data = part.get('body', {}).get('data', '')
    if data:
        return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
    return ''


def get_email_text(payload) -> str:
    mime_type = payload.get('mimeType', '')
    if mime_type == 'text/plain':
        return decode_body(payload)
    if mime_type == 'text/html':
        return decode_body(payload)
    text = ''
    for part in payload.get('parts', []):
        text += get_email_text(part)
    return text


def fetch_jobs(hours_back: int = 48) -> list[dict]:
    logger.info(f'Connecting to Gmail...')
    service = get_gmail_service()

    since = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    query = f'from:jobalerts-noreply@linkedin.com after:{int(since.timestamp())}'

    result = service.users().messages().list(userId='me', q=query, maxResults=50).execute()
    messages = result.get('messages', [])
    logger.info(f'Found {len(messages)} LinkedIn alert emails')

    all_jobs = []
    seen_ids = set()

    for msg_ref in messages:
        msg = service.users().messages().get(userId='me', id=msg_ref['id'], format='full').execute()
        text = get_email_text(msg['payload'])
        urls = extract_job_urls(text)
        for url in urls:
            job_id = re.search(r'/view/(\d+)', url).group(1)
            if job_id not in seen_ids:
                seen_ids.add(job_id)
                all_jobs.append({'job_id': job_id, 'url': url})

    logger.info(f'Extracted {len(all_jobs)} unique job URLs')
    return all_jobs


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    jobs = fetch_jobs()
    print(json.dumps(jobs, indent=2))
