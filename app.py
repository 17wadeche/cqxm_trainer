from __future__ import annotations
import argparse
import base64
import binascii
from concurrent.futures import ThreadPoolExecutor
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4
import webbrowser
from zipfile import ZipFile, ZIP_DEFLATED
from config import DEFAULT_MODEL, DEFAULT_AUTH, SETTINGS_VERSION, PROVIDER, ENVIRONMENT, ENDPOINT, PORT, ROOT, VERSION, MAX_FILE_BYTES, MAX_REQUEST_BYTES, PROCEDURES, BUNDLED_PROCEDURES, data_directory
from bundled_procedures import load_defaults
from engine import ReviewEngine, demo_report
from ingest import source_from_bytes
from mdt import MDTClient, ProviderError, probe_connection
from repository import Repository
def file_payload(value):
    if not isinstance(value, dict):
        raise ValueError("A file is required.")
    name = str(value.get('name', ''))
    if len(name) > 240 or not name:
        raise ValueError("Invalid filename.")
    try:
        data = base64.b64decode(value.get('data', ''), validate=True)
    except (binascii.Error, TypeError, ValueError):
        raise ValueError("The file upload was not valid base64.") from None
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError("Choose a nonempty file smaller than 20 MB.")
    return Path(name).name, data
def checked_text(value, label, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Enter {label} (up to {limit} characters).")
    return value.strip()
class Application:
    def __init__(self, directory, port=PORT, token=None, provider_factory=MDTClient, *, bundled_directory=BUNDLED_PROCEDURES):
        self.directory, self.port = directory, port
        self.token = token or secrets.token_urlsafe(32)
        self.repo = Repository(directory)
        self.procedure_setup_errors = load_defaults(self.repo,bundled_directory) if bundled_directory is not None else []
        self.engine = ReviewEngine(self.repo, provider_factory)
        self.provider_factory = provider_factory
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='gch-review')
        self.jobs, self.captures = {}, {}
        self.connection = {'token': os.environ.get('MDT_GPT_API_TOKEN', ''),
            'model': DEFAULT_MODEL, 'auth_style': DEFAULT_AUTH, 'tested': False,
            'structured_mode': 'auto', 'environment':ENVIRONMENT}
        self.reset_saved_token = False
        self.downloads = Path(os.environ.get('GCH_DOWNLOADS_DIR', Path.home()/'Downloads')).expanduser().resolve()
        self.settings_file = directory/'settings.json'
        if self.settings_file.exists():
            try:
                saved = json.loads(self.settings_file.read_text(encoding='utf-8'))
                if not isinstance(saved, dict):raise ValueError('Invalid saved settings')
                migrated = (saved.get('settings_version') != SETTINGS_VERSION or
                            saved.get('environment') != ENVIRONMENT or saved.get('provider') != PROVIDER or
                            saved.get('model') != DEFAULT_MODEL or saved.get('auth_style') != DEFAULT_AUTH)
                self.reset_saved_token = migrated or saved.get('reset_saved_token') is True
                if self.reset_saved_token:
                    self.connection['token'] = ''
                if saved.get('downloads'):
                    self.downloads = Path(saved['downloads']).expanduser().resolve()
                if saved.get('settings_version') != SETTINGS_VERSION or migrated:
                    self.persist_preferences()
            except (OSError, ValueError, TypeError):
                self.reset_saved_token = True
                self.connection['token'] = ''
        else:
            self.reset_saved_token = True
    def persist_preferences(self):
        self.settings_file.write_text(json.dumps({'settings_version': SETTINGS_VERSION, 'model': self.connection['model'],
            'auth_style': self.connection['auth_style'], 'environment':ENVIRONMENT, 'provider':PROVIDER,
            'reset_saved_token':self.reset_saved_token,
            'downloads': str(self.downloads)}, indent=2), encoding='utf-8')
    def status(self):
        return {'version': VERSION, 'model': self.connection['model'], 'target_model': DEFAULT_MODEL,
            'token_present': bool(self.connection['token']), 'connection_tested': self.connection['tested'],
            'auth_style': self.connection['auth_style'], 'structured_mode': self.connection['structured_mode'],
            'environment':ENVIRONMENT, 'endpoint': ENDPOINT,
            'procedures': self.repo.catalog(), 'expected_procedures': [{'id': i, 'name': n} for i, n in PROCEDURES],
            'procedure_setup_errors': self.procedure_setup_errors,
            'downloads': str(self.downloads), 'data_directory': str(self.directory),
            'procedure_count': len(self.repo.catalog())}
    def ensure_ready(self):
        if not self.connection['token']:
            raise ValueError("Add your MDT-GPT token in Connection before checking a real record.")
        if not self.repo.catalog():
            raise ValueError("Upload the applicable controlled procedures before checking a real record.")
    def _new_job(self, record_id, demo=False):
        job_id = str(uuid4())
        job = {'id': job_id, 'record_id': record_id, 'status': 'queued', 'progress': 0,
               'message': 'Queued', 'result': None, 'error': None, 'demo': demo,
               'cancelled': threading.Event(), 'created_at': time.time()}
        with self.lock:
            active = sum(j['status'] in {'queued', 'running'} for j in self.jobs.values())
            if active >= 2:
                raise ValueError("Two reviews are already running. Wait or cancel a review before starting another.")
            self.jobs[job_id] = job
        return job
    def start_review(self, record_id, stage, policy_selection, files, capture_id=None):
        self.ensure_ready()
        record_id = checked_text(record_id, 'the GCH record ID', 40)
        if not re.fullmatch(r'[A-Za-z0-9_-]{3,40}', record_id):
            raise ValueError('Enter a valid GCH record ID.')
        stage = checked_text(stage, 'the record stage', 120)
        policy_selection = checked_text(policy_selection, 'the procedure revision basis', 500)
        kinds=[f[0] for f in files]
        if len(files) not in {1,2} or sum(k in {'PRIMARY','PESR','DER'} for k in kinds)!=1 or any(k not in {'PRIMARY','PESR','DER','MDR'} for k in kinds) or kinds.count('MDR')>1:
            raise ValueError('Upload one Detailed Event Report or PESR and optionally one matching MDR.')
        job = self._new_job(record_id)
        connection = dict(self.connection)
        def progress(message, percent=None):
            with self.lock:
                job['message'] = message
                if percent is not None:
                    job['progress'] = percent
        def work():
            try:
                with self.lock:
                    job.update(status='running', progress=5, message='Extracting the saved record')
                result = self.engine.run(job['id'], record_id, stage, policy_selection, files,
                                         connection, progress, job['cancelled'])
                if job['cancelled'].is_set():
                    raise InterruptedError()
                with self.lock:
                    job.update(status='ready', progress=100, message='Training review ready', result=result)
            except InterruptedError:
                with self.lock:
                    job.update(status='cancelled', message='Review cancelled', result=None)
            except (ProviderError, ValueError) as exc:
                with self.lock:
                    job.update(status='failed', error=str(exc)[:900], message='The review could not be completed')
            except Exception:
                with self.lock:
                    job.update(status='failed', error='The file could not be processed. Verify the export and supported file type, then try again.', message='The review could not be completed')
            finally:
                connection['token'] = ''
        self.pool.submit(work)
        return self.public_job(job)
    def start_demo(self):
        job = self._new_job('DEMO-001', True)
        try:
            result = demo_report(self.directory, job['id'])
            job.update(status='ready', progress=100, message='Synthetic example ready', result=result)
        except Exception:
            job.update(status='failed', error='Could not create the synthetic example.')
        return self.public_job(job)
    @staticmethod
    def public_job(job):
        return {k: v for k, v in job.items() if k != 'cancelled'}
    def get_job(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError('This review is not available in the current app session.')
            return self.public_job(self.jobs[job_id])
    def capture_start(self, data):
        self.ensure_ready()
        record_id = checked_text(data.get('record_id'), 'the GCH record ID', 40)
        stage = checked_text(data.get('stage'), 'the record stage', 120)
        with self.lock:
            now = time.time()
            self.captures = {k: v for k, v in self.captures.items() if now-v['started'] < 180}
            if self.captures:
                raise ValueError('Another GCH capture is active. Finish or cancel it before starting another.')
            cid = str(uuid4())
            self.captures[cid] = {'record_id': record_id, 'stage': stage, 'started': now, 'claimed': False}
        return {'capture_id': cid, 'expires_in': 180}
    def capture_complete(self, cid, data):
        with self.lock:
            cap = self.captures.get(cid)
            if not cap or time.time()-cap['started'] > 180 or cap['claimed']:
                raise ValueError('The capture expired or has already been processed. Start Check my Work again.')
            path = Path(checked_text(data.get('path'), 'the downloaded file path', 1024)).expanduser().resolve()
            try:
                path.relative_to(self.downloads)
            except ValueError:
                raise ValueError('The export is outside the configured Downloads folder. Use Choose exported report in the extension or update the folder in Connection.') from None
            if not path.is_file() or path.suffix.lower() not in {'.pdf', '.docx', '.txt'}:
                raise ValueError('The downloaded export is not a supported report file.')
            stat = path.stat()
            if stat.st_mtime < cap['started']-3 or stat.st_size > MAX_FILE_BYTES:
                raise ValueError('This is not a fresh export within the file-size limit. Generate the report again.')
            payload = path.read_bytes()
            if len(payload) > MAX_FILE_BYTES:
                raise ValueError('The report exceeds 20 MB.')
            cap['claimed'] = True
        try:
            return self.start_review(cap['record_id'], cap['stage'], 'Uploaded revisions selected by the training owner', [('PRIMARY', path.name, payload)], cid)
        finally:
            with self.lock:
                self.captures.pop(cid, None)
class Handler(BaseHTTPRequestHandler):
    server_version = 'GCHLocal/0.2'
    @property
    def app(self):
        return self.server.application
    def log_message(self, format, *args):
        return  # Never log records, request payloads, or tokens.
    def origin_allowed(self):
        origin = self.headers.get('Origin', '')
        allowed = {f'http://127.0.0.1:{self.app.port}', f'http://localhost:{self.app.port}'}
        return not origin or origin in allowed or bool(re.fullmatch(r'chrome-extension://[a-p]{32}', origin))
    def host_allowed(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.app.port}', f'localhost:{self.app.port}'}
    def send_bytes(self, status, body, mime='application/json', filename=None):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        origin = self.headers.get('Origin')
        if origin and self.origin_allowed():
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
            self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
    def reply(self, value, status=200):
        self.send_bytes(status, json.dumps(value).encode('utf-8'))
    def authorized(self):
        candidate = self.headers.get('Authorization', '')
        return self.host_allowed() and self.origin_allowed() and hmac.compare_digest(candidate, 'Bearer '+self.app.token)
    def payload(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise ValueError('Send application/json.')
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise ValueError('Invalid request length.') from None
        if size <= 0 or size > MAX_REQUEST_BYTES:
            raise ValueError('The request is empty or exceeds the upload limit.')
        result = json.loads(self.rfile.read(size))
        if not isinstance(result, dict):
            raise ValueError('Send a JSON object.')
        return result
    def do_OPTIONS(self):
        if self.host_allowed() and self.origin_allowed():
            self.send_bytes(204, b'')
        else:
            self.reply({'error': 'Origin not allowed'}, 403)
    def do_GET(self):
        path = urlsplit(self.path).path
        static = {'/': 'index.html', '/app.js': 'app.js', '/styles.css': 'styles.css', '/favicon.svg': 'favicon.svg'}
        if path in static and self.host_allowed():
            p = ROOT/'web'/static[path]
            self.send_bytes(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or 'text/plain')
            return
        if not self.authorized():
            self.reply({'error': 'Open the app using the launcher or pair this extension again.'}, 403)
            return
        try:
            if path == '/api/status':
                self.reply(self.app.status())
            elif path == '/api/jobs':
                with self.app.lock:
                    items = [self.app.public_job(j) for j in list(self.app.jobs.values())[-20:]]
                self.reply({'jobs': items})
            elif re.fullmatch(r'/api/jobs/[a-f0-9-]{36}', path):
                self.reply(self.app.get_job(path.split('/')[-1]))
            elif re.fullmatch(r'/api/jobs/[a-f0-9-]{36}/(word|evidence)', path):
                job_id, kind = path.split('/')[-2:]
                job = self.app.get_job(job_id)
                if job['status'] != 'ready':
                    raise ValueError('The review is not ready to download.')
                p = self.app.directory/'reports'/job_id/('review.docx' if kind == 'word' else 'evidence.json')
                self.send_bytes(200, p.read_bytes(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' if kind == 'word' else 'application/json',
                                f"GCH_Training_Review_{job['record_id']}.docx" if kind == 'word' else f"GCH_Evidence_{job['record_id']}.json")
            elif path == '/api/extension':
                output = io.BytesIO()
                with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
                    for p in (ROOT/'extension').iterdir():
                        if p.is_file():
                            archive.write(p, 'GCH_Extension/'+p.name)
                self.send_bytes(200, output.getvalue(), 'application/zip', 'GCH_Extension.zip')
            else:
                self.reply({'error': 'Not found'}, 404)
        except (ValueError, OSError) as exc:
            self.reply({'error': str(exc) if isinstance(exc, ValueError) else 'The requested file is unavailable.'}, 400)
    def do_POST(self):
        if not self.authorized():
            self.reply({'error': 'Open the app using the launcher or pair this extension again.'}, 403)
            return
        path = urlsplit(self.path).path
        try:
            data = self.payload()
            if path == '/api/connection':
                model = checked_text(data.get('model'), 'the MDT-GPT model ID', 120)
                if model != DEFAULT_MODEL:
                    raise ValueError('This build uses '+DEFAULT_MODEL+'.')
                token = data.get('token', '')
                if not isinstance(token, str) or len(token) > 8192 or '\n' in token or '\r' in token:
                    raise ValueError('Invalid token.')
                style = data.get('auth_style', DEFAULT_AUTH)
                if style != DEFAULT_AUTH:
                    raise ValueError('Use Authorization: Bearer for the Production Responses API.')
                environment = ENVIRONMENT
                if data.get('environment', ENVIRONMENT) != ENVIRONMENT:
                    raise ValueError('This build only connects to MDT-GPT Production.')
                with self.app.lock:
                    if environment != self.app.connection['environment']:
                        self.app.connection['token'] = ''
                    self.app.connection.update(model=model, auth_style=style, environment=environment,
                                               tested=False, structured_mode='auto')
                    if token.strip():
                        self.app.connection['token'] = token.strip()
                    downloads = data.get('downloads', '')
                    if downloads:
                        folder = Path(downloads).expanduser().resolve()
                        if folder == Path(folder.anchor) or folder == Path.home().resolve():
                            raise ValueError('Choose a dedicated Downloads folder, not a drive root or your home folder.')
                        self.app.downloads = folder
                    self.app.persist_preferences()
                self.reply(self.app.status())
            elif path == '/api/connection/test':
                cfg = dict(self.app.connection)
                client = self.app.provider_factory(cfg['token'], cfg['model'], cfg['auth_style'],
                    environment=ENVIRONMENT)
                result = probe_connection(client, discover=True)
                self.app.connection.update(result)
                self.app.connection['tested'] = True
                self.app.persist_preferences()
                self.reply({'ok': True, **result})
            elif path == '/api/connection/clear':
                self.app.connection.update(token='', tested=False)
                self.reply({'ok': True})
            elif path == '/api/procedures':
                document_id = checked_text(data.get('document_id'), 'the procedure ID', 40).upper()
                if document_id not in {i for i, _ in PROCEDURES}:
                    raise ValueError('Choose one of the supported procedure IDs.')
                revision = checked_text(data.get('revision'), 'the controlled revision', 80)
                if data.get('approved') is not True:
                    raise ValueError('Confirm that this revision is approved for your training review.')
                name, contents = file_payload(data.get('file'))
                source, warnings = source_from_bytes(name, contents, str(uuid4()), 'procedure', document_id,
                                                      revision=revision, approved=True)
                normalized = re.sub(r'\W', '', '\n'.join(c.text for c in source.chunks)).upper()
                if re.sub(r'\W', '', document_id) not in normalized:
                    raise ValueError('The document ID was not found in the uploaded text. Verify that this is the correct controlled procedure.')
                self.app.repo.put(source, warnings)
                self.reply({'source': {'id': source.id, 'name': source.name}, 'warnings': warnings, 'procedures': self.app.repo.catalog()})
            elif path == '/api/reviews':
                raw_files = data.get('files')
                if not isinstance(raw_files, list) or not 1 <= len(raw_files) <= 2:
                    raise ValueError('Provide a Detailed Event Report or PESR and optionally a matching MDR.')
                if not all(isinstance(value, dict) for value in raw_files):
                    raise ValueError('Provide valid file objects.')
                files = [(value.get('kind'), *file_payload(value)) for value in raw_files]
                self.reply(self.app.start_review(data.get('record_id'), data.get('stage'), data.get('policy_selection'), files), 202)
            elif path == '/api/demo':
                self.reply(self.app.start_demo())
            elif re.fullmatch(r'/api/jobs/[a-f0-9-]{36}/cancel', path):
                jid = path.split('/')[-2]
                with self.app.lock:
                    job = self.app.jobs.get(jid)
                    if not job:
                        raise ValueError('Unknown review.')
                    job['cancelled'].set()
                    if job['status'] in {'queued', 'running'}:
                        job['message'] = 'Cancelling after the current request returns'
                self.reply({'ok': True})
            elif path == '/api/captures':
                self.reply(self.app.capture_start(data))
            elif re.fullmatch(r'/api/captures/[a-f0-9-]{36}/complete', path):
                self.reply(self.app.capture_complete(path.split('/')[-2], data), 202)
            elif re.fullmatch(r'/api/captures/[a-f0-9-]{36}/cancel', path):
                with self.app.lock:
                    self.app.captures.pop(path.split('/')[-2], None)
                self.reply({'ok': True})
            else:
                self.reply({'error': 'Not found'}, 404)
        except (ValueError, ProviderError, KeyError, TypeError, OSError) as exc:
            message = str(exc) if isinstance(exc, (ValueError, ProviderError)) else 'The request could not be processed. Check the inputs and try again.'
            self.reply({'error': message[:1000]}, 400)
    def do_DELETE(self):
        if not self.authorized():
            self.reply({'error': 'Not authorized'}, 403)
            return
        path = urlsplit(self.path).path
        if re.fullmatch(r'/api/procedures/[a-f0-9-]{36}', path):
            self.app.repo.remove(path.split('/')[-1])
            self.reply({'ok': True})
        else:
            self.reply({'error': 'Not found'}, 404)
def make_server(application):
    server = ThreadingHTTPServer(('127.0.0.1', application.port), Handler)
    server.daemon_threads = True
    server.application = application
    application.port = server.server_address[1]
    return server
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--data-dir', type=Path, default=data_directory())
    args = parser.parse_args()
    app = Application(args.data_dir.resolve(), args.port)
    try:
        server = make_server(app)
    except OSError:
        print('The companion cannot start on this port. Close any existing GCH companion window and try again.')
        raise SystemExit(1)
    print(f'GCH Check my Work is running at http://127.0.0.1:{app.port}. Keep this window open. Press Ctrl+C to stop.')
    if not args.no_browser:
        webbrowser.open(f'http://127.0.0.1:{app.port}/#token={app.token}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for job in app.jobs.values():
            job['cancelled'].set()
        app.connection['token'] = ''
        server.server_close()
        app.pool.shutdown(wait=False, cancel_futures=True)
if __name__ == '__main__':
    main()