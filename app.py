from __future__ import annotations
"""
HR Engine — Web control panel (multi-user).

Wraps the existing CLI pipeline (run_pipeline.py) in a Flask app. Each user
(defined in APP_USERS) gets an isolated workspace under DATA_DIR/users/<name>/
holding their own Gmail token, preferences.yaml, CV/CL templates, job data and
generated documents. The pipeline subprocess runs with cwd = that workspace,
so the pipeline code itself stays unmodified.

Auth:    HTTP Basic. APP_USERS="alice:pass1,bob:pass2"
         (or legacy single-user APP_USERNAME/APP_PASSWORD).
Keys:    ANTHROPIC_API_KEY is shared by default; ANTHROPIC_API_KEY_<NAME>
         (username uppercased, '-' → '_') overrides it per user.

Run locally:
  export APP_USERS="me:changeme"
  python3 app.py

Production (Docker entrypoint does this):
  gunicorn --worker-class gthread --threads 16 -b 0.0.0.0:8000 app:app
"""

import collections
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from flask import (Flask, Response, g, jsonify, redirect, request, send_file,
                   send_from_directory, session)
from werkzeug.middleware.proxy_fix import ProxyFix

# ── Paths ───────────────────────────────────────────────────────────────────
# BASE_DIR = where the code lives (read-only in Docker)
# DATA_DIR = persistent state; per-user workspaces live in DATA_DIR/users/
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('DATA_DIR', str(BASE_DIR))).resolve()

GMAIL_SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
DOWNLOAD_DIRS = {'cv': 'cv_output', 'cl': 'cl_output'}
TEMPLATE_NAMES = {'cv': 'CV_template.docx', 'cl': 'CL_template.docx'}


# ── Users ────────────────────────────────────────────────────────────────────
def _parse_users() -> dict[str, str]:
    """APP_USERS="alice:pass1,bob:pass2". Falls back to APP_USERNAME/APP_PASSWORD."""
    users: dict[str, str] = {}
    for pair in os.environ.get('APP_USERS', '').split(','):
        pair = pair.strip()
        if not pair:
            continue
        if ':' not in pair:
            raise ValueError(f'APP_USERS entry "{pair}" must be "username:password"')
        name, password = pair.split(':', 1)
        name = name.strip().lower()
        if not re.fullmatch(r'[a-z0-9_-]{1,32}', name):
            raise ValueError(f'Invalid username "{name}": use a-z, 0-9, "-", "_"')
        if not password:
            raise ValueError(f'Empty password for user "{name}"')
        users[name] = password
    if not users and os.environ.get('APP_PASSWORD'):
        users[os.environ.get('APP_USERNAME', 'admin').lower()] = os.environ['APP_PASSWORD']
    return users


USERS = _parse_users()


def _anthropic_key(user: str) -> str:
    per_user = os.environ.get(f'ANTHROPIC_API_KEY_{user.upper().replace("-", "_")}')
    return per_user or os.environ.get('ANTHROPIC_API_KEY', '')


# ── Workspaces ───────────────────────────────────────────────────────────────
def workspace(user: str) -> Path:
    """Per-user data dir; created and seeded with defaults on first access."""
    ws = DATA_DIR / 'users' / user
    if not (ws / '.initialized').exists():
        for d in ('cv_output', 'cl_output', 'templates'):
            (ws / d).mkdir(parents=True, exist_ok=True)
        for tpl in sorted((BASE_DIR / 'templates').glob('*')):
            dest = ws / 'templates' / tpl.name
            if tpl.is_file() and not dest.exists():
                shutil.copy2(tpl, dest)
        prefs = ws / 'preferences.yaml'
        if not prefs.exists():
            for src in (BASE_DIR / 'preferences.default.yaml', BASE_DIR / 'preferences.yaml'):
                if src.exists():
                    shutil.copy2(src, prefs)
                    break
        (ws / '.initialized').touch()
    return ws


def _migrate_legacy_layout():
    """One-time: move pre-multi-user data into the first listed user's workspace."""
    if not USERS or (DATA_DIR / 'users').exists():
        return
    legacy_files = [f for f in (
        'token.json', 'credentials.json', 'preferences.yaml', 'jobs_detailed.json',
        'jobs_matched.json', 'jobs_rejected.json', 'job_tracker.json', 'tracker.html',
    ) if (DATA_DIR / f).is_file()]
    legacy_dirs = [d for d in ('cv_output', 'cl_output', 'templates')
                   if (DATA_DIR / d).is_dir()]
    if not legacy_files and not legacy_dirs:
        return
    first = next(iter(USERS))
    ws = DATA_DIR / 'users' / first
    ws.mkdir(parents=True)
    for f in legacy_files:
        shutil.copy2(DATA_DIR / f, ws / f)
    for d in legacy_dirs:
        (ws / d).mkdir(exist_ok=True)
        for p in (DATA_DIR / d).iterdir():
            if p.is_file():
                shutil.copy2(p, ws / d / p.name)
    (ws / '.initialized').touch()
    print(f'[hr-engine] Migrated existing single-user data into users/{first}/')


_migrate_legacy_layout()


# ── Flask app + Basic auth ───────────────────────────────────────────────────
app = Flask(__name__, static_folder='static')
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.environ.get(
    'FLASK_SECRET',
    hashlib.sha256(('hr-engine:' + ','.join(f'{u}:{p}' for u, p in sorted(USERS.items()))).encode()).hexdigest(),
)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # template uploads


@app.before_request
def require_auth():
    if request.path == '/healthz':
        return None
    if not USERS:
        return Response('Server misconfigured: set APP_USERS (or APP_PASSWORD).', 500)
    auth = request.authorization
    if auth is not None and auth.type == 'basic':
        name = (auth.username or '').strip().lower()
        expected = USERS.get(name)
        if expected is not None and hmac.compare_digest(auth.password or '', expected):
            g.user = name
            return None
    return Response('Authentication required.', 401,
                    {'WWW-Authenticate': 'Basic realm="HR Engine"'})


@app.get('/healthz')
def healthz():
    return 'ok'


# ── Pipeline runner (one per user; one run at a time server-wide) ───────────
STAGE_FLAGS = {
    'all': [],
    'filter': ['--from-filter'],
    'generate': ['--from-generate'],
    'track': ['--from-track'],
}


class PipelineRunner:
    """Runs run_pipeline.py in the user's workspace; buffers stdout for SSE."""

    def __init__(self, user: str):
        self.user = user
        self.lock = threading.Lock()
        self.buffer: collections.deque[tuple[int, str]] = collections.deque(maxlen=5000)
        self.seq = 0
        self.proc: subprocess.Popen | None = None
        self.stage: str | None = None
        self.started_at: str | None = None
        self.last_exit: int | None = None

    def _append(self, line: str):
        with self.lock:
            self.seq += 1
            self.buffer.append((self.seq, line.rstrip('\n')))

    def since(self, after: int) -> list[tuple[int, str]]:
        with self.lock:
            return [(s, l) for s, l in self.buffer if s > after]

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, stage: str):
        cmd = [sys.executable, '-u', str(BASE_DIR / 'run_pipeline.py')] + STAGE_FLAGS[stage]
        env = dict(os.environ)
        env['PYTHONUNBUFFERED'] = '1'
        env['PYTHONPATH'] = str(BASE_DIR) + os.pathsep + env.get('PYTHONPATH', '')
        env['HR_ENGINE_WEB'] = '1'
        env['ANTHROPIC_API_KEY'] = _anthropic_key(self.user)
        self.proc = subprocess.Popen(
            cmd, cwd=str(workspace(self.user)), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        self.stage = stage
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.last_exit = None
        self._append(f'▶ Starting pipeline (stage: {stage}) ...')
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()

    def _pump(self, proc: subprocess.Popen):
        assert proc.stdout is not None
        for line in proc.stdout:
            self._append(line)
        code = proc.wait()
        self.last_exit = code
        self._append(f'■ Pipeline exited with code {code}')

    def stop(self) -> bool:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            return True
        return False


RUNNERS: dict[str, PipelineRunner] = {}
_runners_lock = threading.Lock()


def get_runner(user: str) -> PipelineRunner:
    with _runners_lock:
        if user not in RUNNERS:
            RUNNERS[user] = PipelineRunner(user)
        return RUNNERS[user]


def busy_user() -> str | None:
    """Chromium + Claude calls are heavy: allow only one run at a time, server-wide."""
    with _runners_lock:
        for u, r in RUNNERS.items():
            if r.running:
                return u
    return None


@app.post('/api/run')
def api_run():
    stage = (request.get_json(silent=True) or {}).get('stage', 'all')
    if stage not in STAGE_FLAGS:
        return jsonify(error=f'Unknown stage: {stage}'), 400
    if not _anthropic_key(g.user):
        return jsonify(error='No Anthropic API key configured for your account.'), 500
    with _runners_lock:
        for u, r in RUNNERS.items():
            if r.running:
                who = 'your' if u == g.user else f'{u}’s'
                return jsonify(error=f'Server is busy: {who} pipeline is running. Try again when it finishes.'), 409
        runner = RUNNERS.setdefault(g.user, PipelineRunner(g.user))
        runner.start(stage)
    return jsonify(status='started')


@app.post('/api/stop')
def api_stop():
    return jsonify(stopped=get_runner(g.user).stop())


@app.get('/api/status')
def api_status():
    runner = get_runner(g.user)
    return jsonify(
        user=g.user,
        running=runner.running,
        stage=runner.stage,
        started_at=runner.started_at,
        last_exit=runner.last_exit,
        busy_user=busy_user(),
        google_connected=(workspace(g.user) / 'token.json').exists(),
        anthropic_key_set=bool(_anthropic_key(g.user)),
        tracker_exists=(workspace(g.user) / 'tracker.html').exists(),
    )


@app.get('/api/logs/stream')
def api_logs_stream():
    """SSE stream of the current user's pipeline output. ?after=<seq> resumes."""
    try:
        after = int(request.args.get('after', request.headers.get('Last-Event-ID', 0)))
    except (TypeError, ValueError):
        after = 0
    runner = get_runner(g.user)

    def generate(last: int):
        yield ': connected\n\n'
        idle = 0.0
        while True:
            items = runner.since(last)
            if items:
                for seq, line in items:
                    last = seq
                    yield f'id: {seq}\ndata: {json.dumps(line)}\n\n'
                idle = 0.0
            else:
                time.sleep(1)
                idle += 1
                if idle >= 15:  # keep proxies from closing the connection
                    idle = 0.0
                    yield ': ping\n\n'

    return Response(generate(after), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# ── UI, tracker, downloads ───────────────────────────────────────────────────
@app.get('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.get('/tracker')
def tracker():
    path = workspace(g.user) / 'tracker.html'
    if not path.exists():
        return ('<p style="font-family:sans-serif;padding:2em">No tracker yet — '
                'run the pipeline first.</p>', 200)
    return send_file(path)


@app.get('/api/files')
def api_files():
    out = []
    ws = workspace(g.user)
    for kind, dirname in DOWNLOAD_DIRS.items():
        d = ws / dirname
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.is_file() and not f.name.startswith('.'):
                out.append({
                    'kind': kind,
                    'name': f.name,
                    'size': f.stat().st_size,
                    'mtime': datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M'),
                    'url': f'/download/{kind}/{f.name}',
                })
    return jsonify(out)


@app.get('/download/<kind>/<path:filename>')
def download(kind, filename):
    if kind not in DOWNLOAD_DIRS:
        return jsonify(error='Unknown file type'), 404
    # send_from_directory rejects path traversal attempts.
    return send_from_directory(workspace(g.user) / DOWNLOAD_DIRS[kind], filename,
                               as_attachment=True)


# ── preferences.yaml editor ──────────────────────────────────────────────────
@app.get('/api/preferences')
def get_preferences():
    path = workspace(g.user) / 'preferences.yaml'
    return jsonify(content=path.read_text() if path.exists() else '')


@app.put('/api/preferences')
def put_preferences():
    content = (request.get_json(silent=True) or {}).get('content', '')
    try:
        yaml.safe_load(content)  # validate before writing
    except yaml.YAMLError as e:
        return jsonify(error=f'Invalid YAML: {e}'), 400
    path = workspace(g.user) / 'preferences.yaml'
    if path.exists():
        path.with_suffix('.yaml.bak').write_text(path.read_text())
    path.write_text(content)
    return jsonify(status='saved')


# ── CV / cover letter templates ──────────────────────────────────────────────
@app.get('/api/templates')
def list_templates():
    out = []
    tdir = workspace(g.user) / 'templates'
    for kind, name in TEMPLATE_NAMES.items():
        f = tdir / name
        if f.exists():
            out.append({'kind': kind, 'name': name, 'size': f.stat().st_size,
                        'mtime': datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M')})
    return jsonify(out)


@app.post('/api/templates')
def upload_template():
    kind = request.form.get('kind', '')
    if kind not in TEMPLATE_NAMES:
        return jsonify(error='kind must be "cv" or "cl"'), 400
    f = request.files.get('file')
    if f is None or not f.filename:
        return jsonify(error='No file uploaded'), 400
    if not f.filename.lower().endswith('.docx'):
        return jsonify(error='Template must be a .docx file'), 400
    head = f.stream.read(2)
    f.stream.seek(0)
    if head != b'PK':  # .docx files are zip archives
        return jsonify(error='File does not look like a valid .docx'), 400
    dest = workspace(g.user) / 'templates' / TEMPLATE_NAMES[kind]
    f.save(dest)
    return jsonify(status='saved', name=TEMPLATE_NAMES[kind])


# ── Google OAuth (web flow, per-user token) ──────────────────────────────────
def _oauth_client_config() -> dict:
    """OAuth client JSON: GOOGLE_CLIENT_JSON env var, or credentials.json on disk."""
    raw = os.environ.get('GOOGLE_CLIENT_JSON')
    if raw:
        return json.loads(raw)
    for path in (workspace(g.user) / 'credentials.json', DATA_DIR / 'credentials.json'):
        if path.exists():
            return json.loads(path.read_text())
    raise FileNotFoundError(
        'No Google OAuth client configured. Set GOOGLE_CLIENT_JSON or place '
        'credentials.json in the data directory.')


def _redirect_uri() -> str:
    base = os.environ.get('PUBLIC_BASE_URL') or request.host_url.rstrip('/')
    base = base.rstrip('/')
    if base.startswith('http://'):  # local development only
        os.environ.setdefault('OAUTHLIB_INSECURE_TRANSPORT', '1')
    return f'{base}/oauth2callback'


@app.get('/auth/google')
def auth_google():
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(_oauth_client_config(), scopes=GMAIL_SCOPES,
                                   redirect_uri=_redirect_uri())
    auth_url, state = flow.authorization_url(
        access_type='offline',          # get a refresh token → pipeline runs unattended
        prompt='consent',               # force refresh token even on re-auth
        include_granted_scopes='true',
    )
    session['oauth_state'] = state
    return redirect(auth_url)


@app.get('/oauth2callback')
def oauth2callback():
    from google_auth_oauthlib.flow import Flow
    os.environ.setdefault('OAUTHLIB_RELAX_TOKEN_SCOPE', '1')
    state = session.get('oauth_state')
    flow = Flow.from_client_config(_oauth_client_config(), scopes=GMAIL_SCOPES,
                                   state=state, redirect_uri=_redirect_uri())
    flow.fetch_token(authorization_response=request.url)
    token_path = workspace(g.user) / 'token.json'
    token_path.write_text(flow.credentials.to_json())
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass
    return redirect('/?google=connected')


@app.post('/auth/google/disconnect')
def auth_google_disconnect():
    token_path = workspace(g.user) / 'token.json'
    if token_path.exists():
        token_path.unlink()
    return jsonify(status='disconnected')


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 8000)), debug=False, threaded=True)
